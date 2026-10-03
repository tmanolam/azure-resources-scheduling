"""Reconciliation orchestrator (T-204).

Ties the engine stages together for one cycle:

  discover -> select -> evaluate desired state -> read actual -> plan diff
           -> order + safety -> execute (unless dry-run)

Key requirements:

- FR-004  Act only when desired != actual (idempotent reconciliation).
- FR-005  Submit start/stop asynchronously; do not wait for completion.
- FR-030  Dry-run logs intended actions without calling start/stop.
- FR-033  Transitional actual states are skipped and retried next cycle.
- NFR-005 Bound parallel ARM calls and back off on HTTP 429 (Retry-After).

Handlers (Phase 3) are injected via a registry mapping handler_key -> Handler.
A Handler exposes get_state(resource) -> actual-state text, start(resource) and
stop(resource) which submit long-running operations without waiting.

Concurrency (NFR-004, single cycle at a time) is enforced by the Functions
timer singleton (host.json) and is out of scope for this pure orchestrator.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field, replace
from typing import Callable, Mapping, Optional, Protocol, Sequence

from . import telemetry
from .evaluator import DesiredState, Profile, evaluate_desired_state
from .models import ActionType, ActualState, PlannedAction, ResourceRecord
from .ordering import OrderingResult, is_transitional, order_and_limit_actions
from .selection import SelectionResult

__all__ = [
    "Handler",
    "ReconcileConfig",
    "CycleSummary",
    "plan_actions",
    "execute_actions",
    "run_reconcile",
]

logger = logging.getLogger("pwrsched.reconcile")


class Handler(Protocol):
    """Common resource-type handler interface (HR-005; implemented in Phase 3)."""

    def get_state(self, resource: ResourceRecord) -> str: ...
    def start(self, resource: ResourceRecord) -> None: ...
    def stop(self, resource: ResourceRecord) -> None: ...


class RetryableThrottling(Exception):
    """Raised by a handler/transport to signal HTTP 429 with a Retry-After hint."""

    def __init__(self, retry_after_seconds: float = 1.0):
        super().__init__("throttled")
        self.retry_after_seconds = retry_after_seconds


@dataclass(frozen=True)
class ReconcileConfig:
    """Runtime configuration for a cycle (loaded from App Configuration)."""

    dry_run: bool = True
    max_actions_per_run: int = 200
    max_parallel_arm_calls: int = 10
    max_throttle_retries: int = 3


@dataclass
class CycleSummary:
    """Per-cycle counters and timing (OBS-002)."""

    run_id: str
    evaluated: int = 0
    started: int = 0
    stopped: int = 0
    skipped: int = 0
    failed: int = 0
    cap_reached: bool = False
    duration_seconds: float = 0.0
    decisions: list[PlannedAction] = field(default_factory=list)


def _desired_to_action(desired: DesiredState, actual: ActualState) -> ActionType:
    """Map (desired, actual) to the action needed, or NONE if already converged (FR-004)."""
    if desired is DesiredState.RUNNING and actual is ActualState.STOPPED:
        return ActionType.START
    if desired is DesiredState.STOPPED and actual is ActualState.RUNNING:
        return ActionType.STOP
    return ActionType.NONE


def _normalise_actual(text: str) -> ActualState:
    """Map a handler's raw state text to a normalised ActualState."""
    if is_transitional(text):
        return ActualState.TRANSITIONAL
    t = (text or "").strip().lower()
    if t in {"running", "started", "succeeded", "ready", "resumed", "online"}:
        return ActualState.RUNNING
    if t in {"stopped", "deallocated", "paused", "shutdown", "offline"}:
        return ActualState.STOPPED
    return ActualState.UNKNOWN


def plan_actions(
    selections: Sequence[SelectionResult],
    *,
    now,
    profile_provider: Callable[[str], Optional[Profile]],
    handlers: Mapping[str, Handler],
) -> list[PlannedAction]:
    """Build planned actions from eligible selections (desired vs actual diff).

    Ineligible selections and converged/transitional/unknown resources produce a
    PlannedAction with ActionType.NONE and a reason so they are still logged.
    """
    planned: list[PlannedAction] = []

    for sel in selections:
        r = sel.resource
        if not sel.eligible:
            planned.append(_none_action(r, sel.reason, sel.profile_name, sel.order or 3))
            continue

        profile = profile_provider(sel.profile_name or "")
        decision = evaluate_desired_state(
            profile,
            now,
            order=sel.order or 3,
            override_state=sel.override_state,
            override_until=sel.override_until,
        )

        if decision.state is DesiredState.NO_ACTION:
            planned.append(
                PlannedAction(r, ActionType.NONE, decision.state.value, decision.reason,
                              sel.profile_name, sel.order or 3, decision.warning)
            )
            continue

        handler = handlers.get(r.handler_key)
        if handler is None:
            planned.append(_none_action(r, "no-handler", sel.profile_name, sel.order or 3))
            continue

        try:
            actual = _normalise_actual(handler.get_state(r))
        except Exception as exc:  # defensive: a read failure must not abort the cycle
            logger.warning("pwrsched.reconcile: get_state failed for %s: %s", r.resource_id, exc)
            planned.append(_none_action(r, "state-read-failed", sel.profile_name, sel.order or 3, decision.warning))
            continue

        if actual is ActualState.TRANSITIONAL:
            planned.append(_none_action(r, "transitional-skip", sel.profile_name, sel.order or 3,
                                        decision.warning, actual_state=actual.value))
            continue
        if actual is ActualState.UNKNOWN:
            planned.append(_none_action(r, "unknown-state-skip", sel.profile_name, sel.order or 3,
                                        decision.warning, actual_state=actual.value))
            continue

        action = _desired_to_action(decision.state, actual)
        reason = decision.reason if action is not ActionType.NONE else "already-converged"
        planned.append(
            PlannedAction(r, action, decision.state.value, reason,
                          sel.profile_name, sel.order or 3, decision.warning,
                          actual_state=actual.value)
        )

    return planned


def _none_action(r, reason, profile_name, order, warning=None, actual_state="Unknown") -> PlannedAction:
    return PlannedAction(r, ActionType.NONE, DesiredState.NO_ACTION.value, reason, profile_name,
                         order, warning, actual_state=actual_state)


def execute_actions(
    ordering: OrderingResult,
    *,
    handlers: Mapping[str, Handler],
    config: ReconcileConfig,
    summary: CycleSummary,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Execute ordered actions, honouring dry-run and 429 back-off.

    In dry-run (FR-030) no handler start/stop is called; the intent is counted
    and logged. Submission is asynchronous (FR-005): handlers must not wait for
    completion. On RetryableThrottling the call is retried up to
    max_throttle_retries, sleeping for the hinted Retry-After (NFR-005).
    """
    for action in ordering.actions:
        handler = handlers.get(action.resource.handler_key)
        if handler is None:
            summary.skipped += 1
            summary.decisions.append(replace(action, result="skipped-no-handler"))
            continue

        if config.dry_run:
            logger.info(
                "pwrsched.decision: DRY-RUN would %s %s (%s)",
                action.action.value, action.resource.resource_id, action.reason,
            )
            _count_success(summary, action.action)
            summary.decisions.append(replace(action, result="dry-run"))
            continue

        if _invoke_with_backoff(handler, action, config, sleep):
            _count_success(summary, action.action)
            summary.decisions.append(replace(action, result="submitted"))
        else:
            summary.failed += 1
            summary.decisions.append(replace(action, result="failed"))

    # Skipped (deny-listed / capped) items are still recorded for the audit log.
    for action in ordering.skipped:
        summary.decisions.append(replace(action, result=action.reason or "skipped"))
    summary.skipped += len(ordering.skipped)
    summary.cap_reached = ordering.cap_reached


def _invoke_with_backoff(handler, action, config, sleep) -> bool:
    """Invoke the handler start/stop with 429 back-off. Returns True on submit."""
    attempts = 0
    while True:
        try:
            if action.action is ActionType.START:
                handler.start(action.resource)
            elif action.action is ActionType.STOP:
                handler.stop(action.resource)
            return True
        except RetryableThrottling as exc:
            attempts += 1
            if attempts > config.max_throttle_retries:
                logger.error(
                    "pwrsched.reconcile: giving up on %s after %d throttled attempts",
                    action.resource.resource_id, attempts,
                )
                return False
            sleep(max(0.0, exc.retry_after_seconds))
        except Exception as exc:  # noqa: BLE001 — one failure must not abort the cycle
            logger.error(
                "pwrsched.reconcile: %s failed for %s: %s",
                action.action.value, action.resource.resource_id, exc,
            )
            return False


def _count_success(summary: CycleSummary, action: ActionType) -> None:
    if action is ActionType.START:
        summary.started += 1
    elif action is ActionType.STOP:
        summary.stopped += 1


def run_reconcile(
    selections: Sequence[SelectionResult],
    *,
    now,
    run_id: str,
    profile_provider: Callable[[str], Optional[Profile]],
    handlers: Mapping[str, Handler],
    config: ReconcileConfig,
    sleep: Callable[[float], None] = time.sleep,
) -> CycleSummary:
    """Run one full reconciliation cycle over pre-selected resources."""
    start_time = time.monotonic()
    summary = CycleSummary(run_id=run_id)

    planned = plan_actions(
        selections, now=now, profile_provider=profile_provider, handlers=handlers
    )
    summary.evaluated = len(planned)

    actionable = [p for p in planned if p.action is not ActionType.NONE]
    non_actionable = [p for p in planned if p.action is ActionType.NONE]
    summary.skipped += len(non_actionable)

    ordering = order_and_limit_actions(
        actionable, max_actions_per_run=config.max_actions_per_run
    )
    execute_actions(ordering, handlers=handlers, config=config, summary=summary, sleep=sleep)

    summary.duration_seconds = time.monotonic() - start_time

    # --- Telemetry (OBS-001/002/005) ----------------------------------------
    # One decision record per evaluated resource: the executed/skipped set is in
    # summary.decisions (with a result); the non-actionable set is logged with
    # its reason as the result.
    for action in summary.decisions:
        telemetry.emit_decision(action, run_id=run_id, dry_run=config.dry_run)
    for action in non_actionable:
        telemetry.emit_decision(action, run_id=run_id, dry_run=config.dry_run)

    if summary.cap_reached:
        deferred = sum(1 for a in ordering.skipped if a.reason == "max-actions-cap")
        telemetry.emit_cap_reached(run_id=run_id, cap=config.max_actions_per_run, deferred=deferred)

    telemetry.emit_summary(
        run_id=run_id,
        evaluated=summary.evaluated,
        started=summary.started,
        stopped=summary.stopped,
        skipped=summary.skipped,
        failed=summary.failed,
        cap_reached=summary.cap_reached,
        duration_seconds=summary.duration_seconds,
    )

    logger.info(
        "pwrsched.summary: run=%s evaluated=%d started=%d stopped=%d skipped=%d failed=%d cap=%s dur=%.3fs",
        summary.run_id, summary.evaluated, summary.started, summary.stopped,
        summary.skipped, summary.failed, summary.cap_reached, summary.duration_seconds,
    )
    return summary
