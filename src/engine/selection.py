"""Resource selection and filtering (T-202).

Takes discovered ResourceRecords and decides which are eligible for scheduling,
resolving tags and applying the hard safety rules:

- FR-013  Tag precedence: resource > resource group > subscription.
- FR-011  Resources under any exclude scope are always skipped.
- FR-012  Only enabled resource types are processed.
- FR-021  schedule-enabled=false opts a resource out.
- BR-002  Opt-in only: a resource must resolve a schedule-profile tag.
- BR-003  Production hard-exclusion: subscription tagged environment=prod is
          always skipped with reason 'production-excluded'. No opt-in exists.
- C1      Fail-safe: when the subscription container could not be read during
          discovery (subscription_container_seen=False), the resource is skipped
          with reason 'subscription-tags-unavailable' rather than assumed
          non-production.

The output is a list of SelectionResult, each either eligible (with the resolved
profile name, order and override tags) or skipped (with a reason), so every
resource produces a log record (OBS-001).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Mapping, Optional, Sequence

from .models import ResourceRecord

__all__ = [
    "SelectionResult",
    "select_resources",
    "resolve_effective_tags",
]

logger = logging.getLogger("pwrsched.selection")

# Tag keys (§6.1).
TAG_PROFILE = "schedule-profile"
TAG_ENABLED = "schedule-enabled"
TAG_OVERRIDE_STATE = "schedule-override-state"
TAG_OVERRIDE_UNTIL = "schedule-override-until"
TAG_ORDER = "schedule-order"

# Production marker (BR-003, A-08).
ENV_TAG = "environment"
PROD_ENV_VALUE = "prod"


@dataclass(frozen=True)
class SelectionResult:
    """Outcome of evaluating one resource for eligibility."""

    resource: ResourceRecord
    eligible: bool
    reason: str
    profile_name: Optional[str] = None
    order: Optional[int] = None
    override_state: Optional[str] = None
    override_until: Optional[str] = None


def resolve_effective_tags(resource: ResourceRecord) -> dict[str, str]:
    """Merge tags with precedence resource > resource group > subscription (FR-013)."""
    merged: dict[str, str] = {}
    merged.update(resource.subscription_tags or {})
    merged.update(resource.resource_group_tags or {})
    merged.update(resource.tags or {})
    return merged


def _get_tag_ci(tags: Optional[Mapping[str, str]], key: str) -> Optional[str]:
    """Look up a tag value by a case-insensitive key (N5).

    Azure tag *names* are case-insensitive, so ``Environment`` and
    ``environment`` are the same tag. The BR-003 production hard-exclusion must
    not depend on exact casing (nor solely on the A-08 policy), so the most
    important safety rule normalises the key before matching.
    """
    if not tags:
        return None
    key_lower = key.lower()
    for k, v in tags.items():
        if str(k).lower() == key_lower:
            return v
    return None


def _is_under_excluded_scope(resource: ResourceRecord, exclude_scopes: Sequence[str]) -> Optional[str]:
    """Return the matching exclude scope if the resource is under one, else None.

    Matches three scope kinds (FR-011):
    - subscription / resource-group / resource ID scopes: by case-insensitive
      equality or path-prefix against the resource ID (and the subscription ID);
    - management-group scopes: by checking whether the excluded MG name appears
      in the resource's subscription ``mg_chain`` (M2), so excluding a child MG
      inside an included MG now works. When ``mg_chain`` is unavailable, MG
      exclusion falls back to being enforced by simply not querying that MG.
    """
    rid = resource.resource_id.lower()
    sub_scope = f"/subscriptions/{resource.subscription_id.lower()}"
    chain = set(resource.mg_chain or ())
    for scope in exclude_scopes:
        s = scope.lower().rstrip("/")
        if not s:
            continue
        if "/managementgroups/" in s:
            mg_name = s.rsplit("/", 1)[-1]
            if mg_name in chain:
                return scope
        elif s.startswith("/subscriptions/"):
            if rid == s or rid.startswith(s + "/") or s == sub_scope:
                return scope
    return None


def _parse_order(value: Optional[str]) -> Optional[int]:
    if value is None:
        return None
    try:
        n = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    if 1 <= n <= 9:
        return n
    return None


def select_resources(
    resources: Sequence[ResourceRecord],
    *,
    enabled_handler_keys: Sequence[str],
    exclude_scopes: Sequence[str] = (),
    default_order_by_handler: Optional[Mapping[str, int]] = None,
) -> list[SelectionResult]:
    """Filter and resolve resources for scheduling.

    Order of checks matters: safety exclusions (production, excluded scope,
    disabled type) are applied before opt-in resolution so a production resource
    is never treated as eligible regardless of its tags (BR-003).
    """
    enabled = set(enabled_handler_keys)
    defaults = dict(default_order_by_handler or {})
    results: list[SelectionResult] = []

    for r in resources:
        effective = resolve_effective_tags(r)

        # C1 fail-safe: if the subscription container could not be read, we
        # cannot confirm the resource is non-production (BR-003). Treat it as
        # ineligible rather than risk acting on a production resource.
        if not r.subscription_container_seen:
            results.append(SelectionResult(r, False, "subscription-tags-unavailable"))
            continue

        # BR-003: production hard-exclusion (checked on subscription tags only,
        # which cannot be overridden by resource/RG tags). The tag key is
        # matched case-insensitively (Azure tag names are case-insensitive, N5).
        env_value = _get_tag_ci(r.subscription_tags, ENV_TAG) or ""
        if env_value.strip().lower() == PROD_ENV_VALUE:
            results.append(SelectionResult(r, False, "production-excluded"))
            continue

        # FR-011: excluded scope.
        matched = _is_under_excluded_scope(r, exclude_scopes)
        if matched is not None:
            results.append(SelectionResult(r, False, "excluded-scope"))
            continue

        # FR-012: disabled resource type.
        if r.handler_key not in enabled:
            results.append(SelectionResult(r, False, "type-not-enabled"))
            continue

        # FR-021: explicit opt-out.
        if effective.get(TAG_ENABLED, "").strip().lower() == "false":
            results.append(SelectionResult(r, False, "schedule-disabled"))
            continue

        # BR-002: opt-in only.
        profile_name = effective.get(TAG_PROFILE, "").strip()
        if not profile_name:
            results.append(SelectionResult(r, False, "no-profile"))
            continue

        order = _parse_order(effective.get(TAG_ORDER)) or defaults.get(r.handler_key, 3)
        results.append(
            SelectionResult(
                resource=r,
                eligible=True,
                reason="eligible",
                profile_name=profile_name,
                order=order,
                override_state=effective.get(TAG_OVERRIDE_STATE),
                override_until=effective.get(TAG_OVERRIDE_UNTIL),
            )
        )

    eligible_count = sum(1 for x in results if x.eligible)
    logger.info(
        "pwrsched.selection: %d eligible of %d resources", eligible_count, len(results)
    )
    return results
