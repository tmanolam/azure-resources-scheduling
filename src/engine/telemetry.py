"""Structured telemetry for the Azure Resource Power Scheduler (T-501).

Emits structured records to Application Insights / Log Analytics so that every
decision and every cycle is queryable (OBS-001, OBS-002) and the alert rules
(OBS-003/004/005) have the fields they key on (SEC-008 auditability).

How it reaches Application Insights
-----------------------------------
Records are written via the standard ``logging`` module. The Azure Monitor
OpenTelemetry distribution (configured once at worker start by
``observability.configure_telemetry``) attaches a ``LoggingHandler`` whose
exporter maps **flat** fields passed through ``extra`` to the ``customDimensions``
column of the ``traces`` table.

Under OpenTelemetry a log attribute value must be a scalar (str/number/bool),
**not** a nested dict. The previous ``extra={"custom_dimensions": {...}}`` form
is an OpenCensus convention that the OpenTelemetry exporter drops, so each field
is emitted as its own flat attribute instead, namespaced ``pwrsched.*`` to avoid
collisions::

    logger.info("pwrsched.decision",
                extra={"pwrsched.event": "pwrsched.decision",
                       "pwrsched.resourceId": "...", ...})

In KQL these appear as ``customDimensions["pwrsched.event"]`` etc. (dotted keys
must be bracket-indexed, not dot-accessed).

Field contract (must match README Step 6 query and infra/modules/monitoring KQL)
--------------------------------------------------------------------------------
Every field is emitted under the ``pwrsched.`` prefix in ``customDimensions``:

* ``pwrsched.decision`` — one per evaluated resource:
    event, runId, resourceId, type, profile, desiredState, actualState,
    action, dryRun, result, error
* ``pwrsched.summary`` — one per cycle:
    event, runId, evaluated, started, stopped, skipped, failed, capReached,
    durationSeconds, converged, desiredRunning, desiredStopped
* ``pwrsched.capReached`` — emitted once when maxActionsPerRun truncates a cycle
  (OBS-005 keys on this event):
    event, runId, cap, deferred

The functions take values as plain types so they are fully unit-testable by
capturing log records; no Azure SDK is required. ``ATTR_PREFIX`` is applied to
every field key so tests and KQL share a single source of truth.
"""

from __future__ import annotations

import logging

from .models import PlannedAction

__all__ = [
    "ATTR_PREFIX",
    "DECISION_EVENT",
    "SUMMARY_EVENT",
    "CAP_REACHED_EVENT",
    "emit_decision",
    "emit_summary",
    "emit_cap_reached",
]

# Dedicated logger name so telemetry can be routed/levelled independently.
logger = logging.getLogger("pwrsched.telemetry")

# Prefix applied to every flat attribute key so OpenTelemetry attributes do not
# collide with other log fields and are easy to select in KQL (H1).
ATTR_PREFIX = "pwrsched."

DECISION_EVENT = "pwrsched.decision"
SUMMARY_EVENT = "pwrsched.summary"
CAP_REACHED_EVENT = "pwrsched.capReached"


def _attrs(**fields) -> dict:
    """Build a flat OpenTelemetry attribute dict (``pwrsched.<field>`` keys).

    None values are dropped (OpenTelemetry attribute values must be scalars and
    an absent field is simply omitted). Booleans are emitted as the lowercase
    strings ``"true"``/``"false"`` (N6): the OpenTelemetry/Application Insights
    pipeline would otherwise surface Python booleans as ``True``/``False`` in
    ``customDimensions``, breaking the README/VERIFICATION expectation that
    ``dryRun`` reads ``true`` and any ``== "true"`` KQL comparison.
    """
    return {
        f"{ATTR_PREFIX}{k}": (str(v).lower() if isinstance(v, bool) else v)
        for k, v in fields.items()
        if v is not None
    }


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
    attrs = _attrs(
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
    logger.info(DECISION_EVENT, extra=attrs)


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
    converged: int = 0,
    desired_running: int = 0,
    desired_stopped: int = 0,
) -> None:
    """Emit one ``pwrsched.summary`` record per cycle (OBS-002, OBS-003).

    From v0.7 (SC-04) it also carries ``converged``, ``desiredRunning`` and
    ``desiredStopped`` so savings reports (hours avoided) work without the
    per-resource ``already-converged`` decision records, which can be suppressed
    for large tenants (``logConvergedDecisions=false``, NFR-011).
    """
    attrs = _attrs(
        event=SUMMARY_EVENT,
        runId=run_id,
        evaluated=evaluated,
        started=started,
        stopped=stopped,
        skipped=skipped,
        failed=failed,
        capReached=cap_reached,
        durationSeconds=round(duration_seconds, 3),
        converged=converged,
        desiredRunning=desired_running,
        desiredStopped=desired_stopped,
    )
    logger.info(SUMMARY_EVENT, extra=attrs)


def emit_cap_reached(*, run_id: str, cap: int, deferred: int) -> None:
    """Emit ``pwrsched.capReached`` when maxActionsPerRun truncates a cycle (OBS-005)."""
    attrs = _attrs(event=CAP_REACHED_EVENT, runId=run_id, cap=cap, deferred=deferred)
    logger.warning(CAP_REACHED_EVENT, extra=attrs)
