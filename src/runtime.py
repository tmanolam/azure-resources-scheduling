"""Azure-backed runtime assembly for the scheduler Function App.

This is the glue that connects the (SDK-free, unit-tested) engine to live Azure:

- a token credential from the user-assigned managed identity (SEC-001);
- configuration loaded from App Configuration (:mod:`engine.config`);
- a Resource Graph ``query_fn`` adapter feeding :func:`engine.discovery.discover_resources`;
- per-handler ARM client factories keyed by subscription, feeding
  :func:`handlers.base.build_registry`.

All Azure SDK imports are lazy and confined to the ``*_factory`` helpers, so the
engine and these builders remain importable and unit-testable without the SDK.
Tests construct :class:`Runtime` directly with fakes via :func:`build_runtime`'s
injection points.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache
from typing import Callable, Mapping, Optional, Sequence

from engine.config import LoadedConfig, load_from_app_configuration
from engine.discovery import QueryPage, discover_resources
from engine.evaluator import Profile
from engine.models import ResourceRecord
from handlers.base import ClientFactory, build_registry

logger = logging.getLogger("pwrsched.runtime")

__all__ = ["Runtime", "build_runtime", "default_client_factories"]


@dataclass
class Runtime:
    """Everything a reconciliation cycle needs, assembled for one invocation."""

    config: LoadedConfig
    handlers: Mapping[str, object]
    _query_fn: Callable[[str, Sequence[str], Optional[str]], QueryPage]

    # Convenience pass-throughs used by function_app._run_cycle.
    @property
    def enabled_handler_keys(self) -> list[str]:
        return self.config.settings.enabled_resource_types

    @property
    def exclude_scopes(self) -> list[str]:
        return self.config.settings.exclude_scopes

    @property
    def include_scopes(self) -> list[str]:
        return self.config.settings.include_scopes

    @property
    def dry_run(self) -> bool:
        return self.config.settings.dry_run

    @property
    def max_actions_per_run(self) -> int:
        return self.config.settings.max_actions_per_run

    def profile_provider(self, name: str) -> Optional[Profile]:
        return self.config.profile_provider(name)

    def discover(self) -> list[ResourceRecord]:
        return discover_resources(
            self._query_fn,
            include_scopes=self.include_scopes,
            enabled_handler_keys=self.enabled_handler_keys,
        )


# Map handler key -> (module path, client class name) for lazy ARM client import.
_ARM_CLIENTS: dict[str, tuple[str, str]] = {
    "vm": ("azure.mgmt.compute", "ComputeManagementClient"),
    "vmss": ("azure.mgmt.compute", "ComputeManagementClient"),
    "aks": ("azure.mgmt.containerservice", "ContainerServiceClient"),
    "postgres-flex": ("azure.mgmt.rdbms.postgresql_flexibleservers", "PostgreSQLManagementClient"),
    "mysql-flex": ("azure.mgmt.rdbms.mysql_flexibleservers", "MySQLManagementClient"),
    "sqlmi": ("azure.mgmt.sql", "SqlManagementClient"),
    "appgw": ("azure.mgmt.network", "NetworkManagementClient"),
}


def _make_client_factory(credential, module_path: str, class_name: str) -> ClientFactory:
    """Build a cached ``(subscription_id) -> ARM client`` factory for one type.

    The client is configured with the azure-core retry policy as the single
    throttling mechanism (M3, NFR-005): HTTP 429 is retried honouring the
    ``Retry-After`` header. ``retry_total`` and ``retry_backoff_max`` tune it.
    """

    @lru_cache(maxsize=None)
    def factory(subscription_id: str):
        import importlib

        module = importlib.import_module(module_path)
        client_cls = getattr(module, class_name)
        return client_cls(
            credential=credential,
            subscription_id=subscription_id,
            retry_total=5,
            retry_backoff_max=60,
        )

    return factory


def default_client_factories(credential, enabled_handler_keys: Sequence[str]) -> dict[str, ClientFactory]:
    """Build ARM client factories for the enabled handler keys."""
    factories: dict[str, ClientFactory] = {}
    for key in enabled_handler_keys:
        spec = _ARM_CLIENTS.get(key)
        if spec is None:
            logger.warning("pwrsched.runtime: no ARM client mapping for handler %r", key)
            continue
        factories[key] = _make_client_factory(credential, spec[0], spec[1])
    return factories


def _classify_scopes(scopes: Sequence[str]) -> tuple[list[str], list[str], list[str]]:
    """Split include scopes into (management_group_names, subscription_ids, rg_filters).

    FR-010 allows include scopes at MG, subscription or resource-group level, but
    Resource Graph's request takes management groups and subscriptions as
    separate parameters. RG scopes are expressed as a subscription + an extra
    ``resourceGroup`` filter clause (M2). Returns:
      - mg_names: last path segment of each ``/managementGroups/<name>`` scope;
      - sub_ids: subscription GUIDs for ``/subscriptions/<id>`` scopes and for
        the parent subscription of any RG scope;
      - rg_filters: lowercased ``<subid>/<rgname>`` keys to filter RG scopes.
    """
    mg_names: list[str] = []
    sub_ids: list[str] = []
    rg_filters: list[str] = []
    for raw in scopes:
        s = (raw or "").strip().rstrip("/")
        low = s.lower()
        if "/managementgroups/" in low:
            mg_names.append(s.rsplit("/", 1)[-1])
        elif "/resourcegroups/" in low:
            # /subscriptions/<sub>/resourceGroups/<rg>
            parts = s.split("/")
            try:
                sub = parts[parts.index("subscriptions") + 1]
                rg = parts[-1]
            except (ValueError, IndexError):
                logger.warning("pwrsched.runtime: unparseable RG scope %r; skipping", raw)
                continue
            sub_ids.append(sub)
            rg_filters.append(f"{sub.lower()}/{rg.lower()}")
        elif low.startswith("/subscriptions/"):
            sub_ids.append(s.rsplit("/", 1)[-1])
        else:
            logger.warning("pwrsched.runtime: unrecognised include scope %r; skipping", raw)
    # De-duplicate while preserving order.
    return (list(dict.fromkeys(mg_names)),
            list(dict.fromkeys(sub_ids)),
            list(dict.fromkeys(rg_filters)))


def _build_resource_graph_query_fn(credential):
    """Return a query_fn adapting azure-mgmt-resourcegraph to discovery's shape.

    Include scopes are split by type (M2): management groups and subscriptions
    go into the request's ``management_groups`` / ``subscriptions`` fields; RG
    scopes are passed as their parent subscription plus a ``resourceGroup``
    filter appended to the query.
    """
    from azure.mgmt.resourcegraph import ResourceGraphClient
    from azure.mgmt.resourcegraph.models import (
        QueryRequest,
        QueryRequestOptions,
    )

    client = ResourceGraphClient(credential=credential)

    def query_fn(query: str, scopes: Sequence[str], skip_token: Optional[str]) -> QueryPage:
        mg_names, sub_ids, rg_filters = _classify_scopes(scopes)

        effective_query = query
        if rg_filters:
            # Keep only rows whose subscription/RG matches one of the requested
            # RG scopes. (MG/subscription scopes are already handled by the
            # request fields; RG scopes additionally narrow within a sub.)
            literals = ", ".join(f"'{f}'" for f in rg_filters)
            effective_query = (
                f"{query} "
                f"| where strcat(tolower(subscriptionId), '/', tolower(resourceGroup)) in ({literals})"
            )

        options = QueryRequestOptions(skip_token=skip_token) if skip_token else QueryRequestOptions()
        request = QueryRequest(
            query=effective_query,
            management_groups=mg_names or None,
            subscriptions=sub_ids or None,
            options=options,
        )
        response = client.resources(request)
        data = response.data if isinstance(response.data, list) else []
        return QueryPage(data=data, skip_token=getattr(response, "skip_token", None))

    return query_fn


def build_runtime(
    app_config_endpoint: str,
    *,
    credential=None,
    config: Optional[LoadedConfig] = None,
    query_fn=None,
    client_factories: Optional[Mapping[str, ClientFactory]] = None,
) -> Runtime:
    """Assemble a :class:`Runtime` for one cycle.

    In production only ``app_config_endpoint`` is passed and everything is built
    from the managed identity. Tests inject ``config``, ``query_fn`` and/or
    ``client_factories`` to avoid any Azure SDK dependency.
    """
    if credential is None and (config is None or query_fn is None or client_factories is None):
        from azure.identity import DefaultAzureCredential

        credential = DefaultAzureCredential()

    if config is None:
        config = load_from_app_configuration(app_config_endpoint, credential=credential)

    enabled = config.settings.enabled_resource_types

    if query_fn is None:
        query_fn = _build_resource_graph_query_fn(credential)

    if client_factories is None:
        client_factories = default_client_factories(credential, enabled)

    handlers = build_registry(list(enabled), client_factories)

    logger.info(
        "pwrsched.runtime: built runtime — %d handler(s), %d profile(s), dryRun=%s",
        len(handlers), len(config.profiles), config.settings.dry_run,
    )
    return Runtime(config=config, handlers=handlers, _query_fn=query_fn)
