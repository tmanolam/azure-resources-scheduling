"""Azure Resource Graph discovery (T-201).

Queries Resource Graph across the configured include scopes for resources whose
type maps to an enabled handler, and normalises them into ResourceRecord
instances (FR-010). Paging beyond 1,000 results is handled via the skip token
(FR-014).

To keep this unit-testable without the Azure SDK, the Resource Graph call is
injected as a ``query_fn`` callable with the signature:

    query_fn(query: str, scopes: list[str], skip_token: str | None) -> QueryPage

where QueryPage has ``.data`` (an iterable of row mappings) and ``.skip_token``
(str or None). The production wiring in ``build_resource_graph_query_fn`` adapts
``azure.mgmt.resourcegraph`` to this shape.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable, Iterable, Mapping, Optional, Protocol, Sequence

from .models import ResourceRecord

__all__ = [
    "HANDLER_BY_TYPE",
    "TYPE_BY_HANDLER",
    "QueryPage",
    "discover_resources",
    "build_kql_query",
]

logger = logging.getLogger("pwrsched.discovery")

# ARM resource type (lowercased) -> engine handler key (§8.1).
HANDLER_BY_TYPE: dict[str, str] = {
    "microsoft.compute/virtualmachines": "vm",
    "microsoft.compute/virtualmachinescalesets": "vmss",
    "microsoft.containerservice/managedclusters": "aks",
    "microsoft.dbforpostgresql/flexibleservers": "postgres-flex",
    "microsoft.dbformysql/flexibleservers": "mysql-flex",
    "microsoft.sql/managedinstances": "sqlmi",
    "microsoft.network/applicationgateways": "appgw",
}

# Reverse map handler key -> ARM type (original casing for KQL readability).
TYPE_BY_HANDLER: dict[str, str] = {
    "vm": "Microsoft.Compute/virtualMachines",
    "vmss": "Microsoft.Compute/virtualMachineScaleSets",
    "aks": "Microsoft.ContainerService/managedClusters",
    "postgres-flex": "Microsoft.DBforPostgreSQL/flexibleServers",
    "mysql-flex": "Microsoft.DBforMySQL/flexibleServers",
    "sqlmi": "Microsoft.Sql/managedInstances",
    "appgw": "Microsoft.Network/applicationGateways",
}


@dataclass(frozen=True)
class QueryPage:
    """One page of Resource Graph results."""

    data: Iterable[Mapping[str, object]]
    skip_token: Optional[str] = None


class QueryFn(Protocol):
    def __call__(
        self, query: str, scopes: Sequence[str], skip_token: Optional[str]
    ) -> QueryPage: ...


def build_kql_query(enabled_handler_keys: Sequence[str]) -> str:
    """Build the KQL query that returns only enabled, tagged resource types.

    Only resources carrying a ``schedule-profile`` tag are returned (BR-002:
    opt-in only), reducing the result set before engine-side filtering.
    """
    enabled_types = [
        TYPE_BY_HANDLER[k] for k in enabled_handler_keys if k in TYPE_BY_HANDLER
    ]
    # Represent the type list as a KQL dynamic array membership test.
    types_literal = ", ".join(f"'{t.lower()}'" for t in enabled_types)
    return (
        "Resources "
        f"| where tolower(type) in ({types_literal}) "
        "| where isnotempty(tags['schedule-profile']) "
        "| project id, type, subscriptionId, resourceGroup, location, tags"
    )


def _max_pages_guard(n: int) -> None:
    if n > 10_000:
        raise RuntimeError("Resource Graph paging exceeded 10,000 pages; aborting")


def discover_resources(
    query_fn: QueryFn,
    *,
    include_scopes: Sequence[str],
    enabled_handler_keys: Sequence[str],
    page_handler: Optional[Callable[[int], None]] = None,
) -> list[ResourceRecord]:
    """Discover opted-in resources across include scopes, following paging.

    Args:
        query_fn: Injected Resource Graph executor (see module docstring).
        include_scopes: Management group / subscription / RG IDs to query (FR-010).
        enabled_handler_keys: Handler keys enabled in settings (FR-012 pre-filter).
        page_handler: Optional callback invoked with each page index (telemetry).

    Returns:
        A list of normalised ResourceRecord. Rows with an unmappable type are
        skipped defensively (should not happen given the KQL filter).
    """
    query = build_kql_query(enabled_handler_keys)
    records: list[ResourceRecord] = []
    skip_token: Optional[str] = None
    page_index = 0

    while True:
        _max_pages_guard(page_index)
        page = query_fn(query, list(include_scopes), skip_token)
        if page_handler is not None:
            page_handler(page_index)

        for row in page.data:
            record = _row_to_record(row)
            if record is not None:
                records.append(record)

        skip_token = page.skip_token
        page_index += 1
        if not skip_token:
            break

    logger.info(
        "pwrsched.discovery: discovered %d resource(s) across %d page(s)",
        len(records),
        page_index,
    )
    return records


def _row_to_record(row: Mapping[str, object]) -> Optional[ResourceRecord]:
    """Convert one Resource Graph row into a ResourceRecord, or None if invalid."""
    resource_id = row.get("id")
    resource_type = row.get("type")
    if not isinstance(resource_id, str) or not isinstance(resource_type, str):
        logger.warning("pwrsched.discovery: skipping row with missing id/type: %r", row)
        return None

    handler_key = HANDLER_BY_TYPE.get(resource_type.lower())
    if handler_key is None:
        logger.warning(
            "pwrsched.discovery: no handler for type %s; skipping %s",
            resource_type,
            resource_id,
        )
        return None

    tags_raw = row.get("tags") or {}
    tags = {str(k): str(v) for k, v in tags_raw.items()} if isinstance(tags_raw, Mapping) else {}

    return ResourceRecord(
        resource_id=resource_id,
        resource_type=resource_type,
        handler_key=handler_key,
        subscription_id=str(row.get("subscriptionId", "")),
        resource_group=str(row.get("resourceGroup", "")),
        location=str(row.get("location", "")),
        tags=tags,
    )
