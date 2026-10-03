"""Action ordering and safety controls (T-203).

Given the per-resource start/stop decisions, this module:

- FR-006  Orders starts ascending and stops descending by schedule-order.
- FR-032  Refuses a hard-coded deny list of resource types regardless of config.
- FR-033  Skips resources in a transitional state (retried next cycle).
- FR-031  Caps actions at maxActionsPerRun and signals an alert when reached.
- FR-030  Dry-run is handled by the executor (T-204); this module only plans.

The deny list is defence-in-depth alongside RBAC scoping and the exclude list
(BR-001, R-01): even if one of these types were somehow discovered, it is never
acted on.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Sequence

from .models import ActionType, PlannedAction

__all__ = [
    "DENY_LISTED_TYPES",
    "TRANSITIONAL_TOKENS",
    "OrderingResult",
    "order_and_limit_actions",
    "is_transitional",
]

logger = logging.getLogger("pwrsched.ordering")

# FR-032: hard deny list (lowercased ARM types). Never acted on.
DENY_LISTED_TYPES: frozenset[str] = frozenset(
    {
        "microsoft.network/azurefirewalls",
        "microsoft.network/virtualnetworkgateways",
        "microsoft.network/expressroutecircuits",
        "microsoft.network/bastionhosts",
    }
)

# FR-033: substrings that indicate a transitional provisioning/power state.
TRANSITIONAL_TOKENS: frozenset[str] = frozenset(
    {"starting", "stopping", "updating", "deleting", "creating", "deallocating"}
)


@dataclass(frozen=True)
class OrderingResult:
    """Planned actions after ordering + safety filtering.

    Attributes:
        actions: Actions to execute, in execution order.
        skipped: Actions removed by safety rules, each carrying a reason.
        cap_reached: True if maxActionsPerRun truncated the list (FR-031 alert).
    """

    actions: tuple[PlannedAction, ...]
    skipped: tuple[PlannedAction, ...]
    cap_reached: bool


def is_transitional(actual_state_text: str) -> bool:
    """Return True if the actual-state text indicates a transitional state."""
    text = (actual_state_text or "").strip().lower()
    return any(token in text for token in TRANSITIONAL_TOKENS)


def _deny(action: PlannedAction) -> bool:
    return action.resource.resource_type.lower() in DENY_LISTED_TYPES


def order_and_limit_actions(
    actions: Sequence[PlannedAction],
    *,
    max_actions_per_run: int,
) -> OrderingResult:
    """Order actionable items and apply the per-run cap.

    Only actions with ActionType.START or STOP are considered; NONE items are
    assumed already filtered out by the caller. Deny-listed types are dropped
    into ``skipped`` with reason 'deny-listed-type' (FR-032).

    Ordering (FR-006):
      - starts first, ascending schedule-order (databases before apps);
      - stops next, descending schedule-order (apps before databases).
    This yields a safe start/stop sequence within one cycle.
    """
    actionable: list[PlannedAction] = []
    skipped: list[PlannedAction] = []

    for a in actions:
        if a.action is ActionType.NONE:
            continue
        if _deny(a):
            logger.warning(
                "pwrsched.ordering: deny-listed type %s skipped (%s)",
                a.resource.resource_type,
                a.resource.resource_id,
            )
            skipped.append(_with_reason(a, "deny-listed-type"))
            continue
        actionable.append(a)

    starts = sorted(
        (a for a in actionable if a.action is ActionType.START),
        key=lambda a: (a.order, a.resource.resource_id),
    )
    stops = sorted(
        (a for a in actionable if a.action is ActionType.STOP),
        key=lambda a: (-a.order, a.resource.resource_id),
    )
    ordered = starts + stops

    cap_reached = False
    if max_actions_per_run >= 0 and len(ordered) > max_actions_per_run:
        cap_reached = True
        over = ordered[max_actions_per_run:]
        ordered = ordered[:max_actions_per_run]
        for a in over:
            skipped.append(_with_reason(a, "max-actions-cap"))
        logger.warning(
            "pwrsched.ordering: maxActionsPerRun=%d reached; %d action(s) deferred (FR-031)",
            max_actions_per_run,
            len(over),
        )

    return OrderingResult(tuple(ordered), tuple(skipped), cap_reached)


def _with_reason(action: PlannedAction, reason: str) -> PlannedAction:
    """Return a copy of the action with a safety reason, action downgraded to NONE."""
    from dataclasses import replace

    return replace(action, action=ActionType.NONE, reason=reason)
