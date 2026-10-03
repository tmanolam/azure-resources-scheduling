"""Structured telemetry for the Azure Resource Power Scheduler (T-501).

Emits structured records to Application Insights / Log Analytics so that every
decision and every cycle is queryable (OBS-001, OBS-002) and the alert rules
(OBS-003/004/005) have the fields they key on (SEC-008 auditability).

How it reaches Application Insights
-----------------------------------
Records are written via the standard ``logging`` module with a
``custom_dimensions`` dict passed through ``extra``. The Azure Monitor /
OpenCensus log handler configured by the Functions host maps that dict to the
``customDimensions`` column, so a record emitted here as::

    logger.info("pwrsched.decision", extra={"custom_dimensions": {...}})

is queryable in KQL as ``traces | where customDimensions.event == "..."``.

Field contract (must match README Step 6 query and infra/modules/monitoring KQL)
--------------------------------------------------------------------------------
* ``pwrsched.decision`` — one per evaluated resource:
    event, runId, resourceId, type, profile, desiredState, actualState,
    action, dryRun, result, error
* ``pwrsched.summary`` — one per cycle:
    event, runId, evaluated, started, stopped, skipped, failed, capReached,
    durationSeconds
* ``pwrsched.capReached`` — emitted once when maxActionsPerRun truncates a cycle
  (OBS-005 keys on this event):
    event, runId, cap, deferred

The functions take values as plain types so they are fully unit-testable by
capturing log records; no Azure SDK is required.
"""

from __future__ import annotations

import logging
from typing import Optional

from .models import PlannedAction

__all__ = [
    "DECISION_EVENT",
    "SUMMARY_EVENT",
    "CAP_REACHED_EVENT",
    "emit_decision",
    "emit_summary",
    "emit_cap_reached",
]

# Dedicated logger name so telemetry can be routed/levelled independently.
logger = logging.getLogger("pwrsched.telemetry")

DECISION_EVENT = "pwrsched.decision"
SUMMARY_EVENT = "pwrsched.summary"
CAP_REACHED_EVENT = "pwrsched.capReached"


def _dims(**fields) -> dict:
    """Build a custom_dimensions dict, dropping None values for cleanliness."""
    return {k: v for k, v in fields.items() if v is not None}


def emit_decision(
    action: PlannedAction,
    *,
    run_id: str,
    dry_run: bool,
) -> None:
    """Emit one ``pwrsched.decision`` record for an evaluated resource (OBS-001).

    ``result`` defaults from the action when not already set by the executor:
    an actionable item that reached here un-executed is 'planned'; a NONE action
    carries its skip/no-action reason as the result.
    """
    r = action.resource
    result = action.result or ("planned" if action.action.value != "none" else action.reason)
    dims = _dims(
        event=DECISION_EVENT,
        runId=run_id,
        resourceId=r.resource_id,
        type=r.resource_type,
        profile=action.profile_name,
        desiredState=action.desired_state,
        actualState=action.actual_state,
        action=action.action.value,
        dryRun=dry_run,
        result=result,
        error=action.warning,
    )
    logger.info(DECISION_EVENT, extra={"custom_dimensions": dims})


def emit_summary(
    *,
    run_id: str,
    evaluated: int,
    started: int,
    stopped: int,
    skipped: int,
    failed: int,
    cap_reached: bool,
    duration_seconds: float,
) -> None:
    """Emit one ``pwrsched.summary`` record per cycle (OBS-002, OBS-003)."""
    dims = _dims(
        event=SUMMARY_EVENT,
        runId=run_id,
        evaluated=evaluated,
        started=started,
        stopped=stopped,
        skipped=skipped,
        failed=failed,
        capReached=cap_reached,
        durationSeconds=round(duration_seconds, 3),
    )
    logger.info(SUMMARY_EVENT, extra={"custom_dimensions": dims})


def emit_cap_reached(*, run_id: str, cap: int, deferred: int) -> None:
    """Emit ``pwrsched.capReached`` when maxActionsPerRun truncates a cycle (OBS-005)."""
    dims = _dims(event=CAP_REACHED_EVENT, runId=run_id, cap=cap, deferred=deferred)
    logger.warning(CAP_REACHED_EVENT, extra={"custom_dimensions": dims})
