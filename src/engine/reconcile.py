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
from concurrent.futures import ThreadPoolExecutor
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


@dataclass(frozen=True)
class ReconcileConfig:
    """Runtime configuration for a cycle (loaded from App Configuration)."""

    dry_run: bool = True
    max_actions_per_run: int = 200
    # Bounds the ThreadPoolExecutor that reads/confirms actual state via ARM for
    # resources without a Resource Graph power state (M1/N7). See
    # ``_prefetch_fallback_states``.
    max_parallel_arm_calls: int = 10
    # SC-01 (FR-034): bounds the ThreadPoolExecutor that *submits* start/stop
    # operations. Submission is per order group with a barrier between groups
    # (all order-1 submissions finish before order-2 begins), so dependency
    # ordering is preserved while a large cap clears within the function timeout.
    max_parallel_actions: int = 10
    # SC-04 (NFR-011): when False, per-resource ``already-converged`` decision
    # records are not emitted (only counted in the summary), to keep telemetry
    # volume proportional to the number of actions, not resources. Recommended
    # False above ~1,000 in-scope resources. Default True = unchanged behaviour.
    log_converged_decisions: bool = True


@dataclass(frozen=True)
class InvokeOutcome:
    """Result of invoking a handler start/stop (H3).

    Exactly one of these states applies:
    - ``submitted`` True: the operation was submitted;
    - ``skip_reason`` set: the handler raised HandlerSkip (skip, no retry);
    - both falsy: a genuine failure.
    """

    submitted: bool = False
    skip_reason: Optional[str] = None


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
    # SC-04 (OBS-002, NFR-011): aggregate counts so savings reporting (hours
    # avoided) works even when per-resource ``already-converged`` decision
    # records are suppressed (``log_converged_decisions=False``).
    converged: int = 0
    desired_running: int = 0
    desired_stopped: int = 0
    decisions: list[PlannedAction] = field(default_factory=list)


def _desired_to_action(desired: DesiredState, actual: ActualState) -> ActionType:
    """Map (desired, actual) to the action needed, or NONE if already converged (FR-004).

    STOPPED_ALLOCATED (a VM/VMSS powered off from inside the OS but still
    allocated and billed) is treated as "not yet converged" when the desired
    state is Stopped: it must be deallocated to actually save cost (H4).
    """
    if desired is DesiredState.RUNNING and actual in (ActualState.STOPPED, ActualState.STOPPED_ALLOCATED):
        return ActionType.START
    if desired is DesiredState.STOPPED and actual in (ActualState.RUNNING, ActualState.STOPPED_ALLOCATED):
        return ActionType.STOP
    return ActionType.NONE


def _normalise_actual(text: str) -> ActualState:
    """Map a handler's raw state text to a normalised ActualState.

    VM/VMSS handlers report ``stopped-allocated`` for an OS-level shutdown that
    is still billed (distinct from ``deallocated``), so it maps to
    STOPPED_ALLOCATED (H4). Database ``Stopped`` means fully stopped → STOPPED.
    """
    t = (text or "").strip().lower()
    if t in {"stopped-allocated", "stoppedallocated"}:
        return ActualState.STOPPED_ALLOCATED
    if is_transitional(text):
        return ActualState.TRANSITIONAL
    if t in {"running", "started", "ready", "resumed", "online"}:
        return ActualState.RUNNING
    if t in {"stopped", "deallocated", "paused", "shutdown", "offline"}:
        return ActualState.STOPPED
    return ActualState.UNKNOWN


# Handler keys whose plain 'stopped' power state means "powered off but still
# allocated/billed" and must be deallocated (H4). For these, a Resource Graph
# 'stopped' is mapped to 'stopped-allocated' before normalisation.
_ALLOCATED_WHEN_STOPPED = frozenset({"vm", "vmss"})


def _read_actual_state(resource: ResourceRecord, handler: "Handler") -> ActualState:
    """Determine the actual state, preferring the Resource Graph read (M1).

    When discovery populated ``resource.power_state`` (the common case), no
    per-resource ARM call is made — this is what keeps a large cycle within the
    10-minute budget (NFR-002; 12-minute function timeout). Only when it is absent do we fall back to the
    handler's ARM ``get_state``. The handler's ``start``/``stop`` still issues
    the authoritative ARM operation, so a slightly stale read self-heals next
    cycle (FR-004).
    """
    raw = (resource.power_state or "").strip()
    if not raw:
        return _normalise_actual(handler.get_state(resource))
    # Apply the VM/VMSS billed-while-stopped distinction (H4) to the RG value.
    if resource.handler_key in _ALLOCATED_WHEN_STOPPED and raw.lower() == "stopped":
        raw = "stopped-allocated"
    return _normalise_actual(raw)


def _needs_fallback_read(resource: ResourceRecord) -> bool:
    """True when actual state is not in Resource Graph and needs a handler read.

    These are the only resources that incur a per-resource ARM ``get_state``
    call (e.g. VM scale sets, which have no power state in Resource Graph).
    """
    return not (resource.power_state or "").strip()


def _prefetch_fallback_states(
    selections: Sequence[SelectionResult],
    handlers: Mapping[str, Handler],
    max_parallel_arm_calls: int,
) -> tuple[dict[str, ActualState], dict[str, str]]:
    """Read actual state for fallback resources concurrently (N7, M1).

    Only resources whose state is absent from Resource Graph
    (:func:`_needs_fallback_read`) need an ARM ``get_state`` call. Those reads
    are independent and I/O-bound, so they run in a bounded ``ThreadPoolExecutor``
    sized by ``max_parallel_arm_calls`` (NFR-005) instead of sequentially, which
    keeps a large cycle within the 10-minute budget (NFR-002; 12-minute function timeout).

    Returns two maps for the fallback resources only:

    - ``states``: resource_id -> ActualState for reads that succeeded.
    - ``skips``: resource_id -> reason when ``get_state`` raised ``HandlerSkip``
      (e.g. a Flexible scale set, V3/HR-008). These are logged as a skip, not
      ``state-read-failed`` (HR-001/HR-004).

    A resource that is in neither map had a genuine read failure; the planner
    records ``state-read-failed`` for it.
    """
    targets = [
        sel.resource
        for sel in selections
        if sel.eligible
        and handlers.get(sel.resource.handler_key) is not None
        and _needs_fallback_read(sel.resource)
    ]
    if not targets:
        return {}, {}

    # Deduplicate by resource_id to avoid reading the same resource twice.
    unique: dict[str, ResourceRecord] = {r.resource_id: r for r in targets}
    workers = max(1, min(int(max_parallel_arm_calls or 1), len(unique)))

    def _read(r: ResourceRecord) -> tuple[str, Optional[ActualState], Optional[str]]:
        handler = handlers[r.handler_key]
        try:
            return r.resource_id, _normalise_actual(handler.get_state(r)), None
        except Exception as exc:  # defensive: a read failure must not abort the cycle
            skip_reason = _handler_skip_reason(exc)
            if skip_reason is not None:
                # Expected skip (HR-001/HR-004/HR-008), not a failure.
                return r.resource_id, None, skip_reason
            logger.warning("pwrsched.reconcile: get_state failed for %s: %s", r.resource_id, exc)
            return r.resource_id, None, None

    states: dict[str, ActualState] = {}
    skips: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="arm-getstate") as pool:
        for rid, state, skip_reason in pool.map(_read, unique.values()):
            if state is not None:
                states[rid] = state
            elif skip_reason is not None:
                skips[rid] = skip_reason
    return states, skips


def plan_actions(
    selections: Sequence[SelectionResult],
    *,
    now,
    profile_provider: Callable[[str], Optional[Profile]],
    handlers: Mapping[str, Handler],
    max_parallel_arm_calls: int = 10,
) -> list[PlannedAction]:
    """Build planned actions from eligible selections (desired vs actual diff).

    Ineligible selections and converged/transitional/unknown resources produce a
    PlannedAction with ActionType.NONE and a reason so they are still logged.

    Resources whose actual state is not available from Resource Graph need a
    per-resource ARM ``get_state`` read; those reads are performed up front in a
    bounded thread pool sized by ``max_parallel_arm_calls`` (N7, NFR-005) so a
    large cycle stays within the 10-minute budget (NFR-002; 12-minute function timeout).
    """
    planned: list[PlannedAction] = []

    # N7: prefetch the fallback (ARM) state reads concurrently; resources with a
    # Resource Graph power state are resolved directly below without an ARM call.
    fallback_states, fallback_skips = _prefetch_fallback_states(
        selections, handlers, max_parallel_arm_calls
    )

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

        if _needs_fallback_read(r):
            # Resolved by the prefetch pool. Absent => either the handler asked to
            # skip (HandlerSkip, e.g. a Flexible scale set — V3/HR-008) or the read
            # failed. A skip is logged as skipped:<reason>, not state-read-failed, so
            # it is not counted as a failure or retried (HR-001/HR-004). The
            # `skipped:` prefix (not `skip:`) matches execution-time skips
            # (execute_actions, H3) and the day-2 workbook's "Failed or skipped"
            # panel, which filters `result startswith "skipped"` (V3 follow-up).
            actual = fallback_states.get(r.resource_id)
            if actual is None:
                skip_reason = fallback_skips.get(r.resource_id)
                reason = f"skipped:{skip_reason}" if skip_reason else "state-read-failed"
                planned.append(_none_action(r, reason, sel.profile_name,
                                            sel.order or 3, decision.warning))
                continue
        else:
            # Resource Graph power state (M1): pure, no ARM call.
            actual = _read_actual_state(r, handler)

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
    """Execute ordered actions, honouring dry-run.

    In dry-run (FR-030) no handler start/stop is called; the intent is counted
    and logged. Submission is asynchronous (FR-005): handlers must not wait for
    completion.

    Parallel submission (SC-01, FR-034): outside dry-run the ordered actions are
    submitted through a bounded ``ThreadPoolExecutor`` (``max_parallel_actions``)
    **per order group**, with a barrier between groups — all actions in one
    ``(ActionType, schedule-order)`` group finish submitting before the next
    group starts. ``order_and_limit_actions`` already produces starts ascending
    by order then stops descending by order and applies the single
    ``maxActionsPerRun`` cap (D-09), so grouping on consecutive
    ``(action, order)`` preserves the dependency sequence (databases start before
    apps; apps stop before databases) while parallelising within a group. This
    lets a cycle submit the capped number of actions well within the function
    timeout (NFR-002). Per-action failures stay isolated.

    Dry-run keeps the simple sequential path (no ARM calls, so there is nothing
    to parallelise and the log order is stable).

    Throttling (NFR-005): HTTP 429 is retried by the Azure SDK's own retry
    policy (azure-core), honouring the ``Retry-After`` header — see
    ``runtime.default_client_factories`` which configures ``retry_total`` /
    ``retry_backoff_max`` on the ARM clients. The engine does not implement a
    second back-off mechanism (finding M3). ``sleep`` is retained only for
    backward-compatible call sites and is unused.
    """
    if config.dry_run:
        for action in ordering.actions:
            handler = handlers.get(action.resource.handler_key)
            if handler is None:
                summary.skipped += 1
                summary.decisions.append(replace(action, result="skipped-no-handler"))
                continue
            logger.info(
                "pwrsched.decision: DRY-RUN would %s %s (%s)",
                action.action.value, action.resource.resource_id, action.reason,
            )
            _count_success(summary, action.action)
            summary.decisions.append(replace(action, result="dry-run"))
        _record_skipped(ordering, summary)
        return

    # Live: submit per order group (barrier between groups), bounded concurrency.
    workers = max(1, int(config.max_parallel_actions or 1))
    for group in _group_by_order(ordering.actions):
        _submit_group(group, handlers=handlers, summary=summary, workers=workers)

    _record_skipped(ordering, summary)


def _group_by_order(actions: Sequence[PlannedAction]) -> list[list[PlannedAction]]:
    """Split the ordered action list into consecutive ``(action, order)`` groups.

    ``order_and_limit_actions`` emits starts (ascending order) then stops
    (descending order); consecutive actions sharing the same ``(ActionType,
    order)`` form one group that may be submitted in parallel. A change in
    either the action type or the order number starts a new group, which the
    caller runs only after the previous group's submissions complete — the
    dependency barrier (FR-006).
    """
    groups: list[list[PlannedAction]] = []
    current: list[PlannedAction] = []
    key = None
    for a in actions:
        a_key = (a.action, a.order)
        if a_key != key:
            if current:
                groups.append(current)
            current = [a]
            key = a_key
        else:
            current.append(a)
    if current:
        groups.append(current)
    return groups


def _submit_group(
    group: Sequence[PlannedAction],
    *,
    handlers: Mapping[str, Handler],
    summary: CycleSummary,
    workers: int,
) -> None:
    """Submit one order group concurrently and fold the outcomes into the summary.

    Results are collected and applied to ``summary`` on the calling thread, so
    the mutable ``CycleSummary`` is never touched from worker threads. A single
    action's failure is isolated — it does not stop the rest of the group.
    """
    pool_workers = max(1, min(workers, len(group)))

    def _run(action: PlannedAction) -> tuple[PlannedAction, Optional[InvokeOutcome]]:
        handler = handlers.get(action.resource.handler_key)
        if handler is None:
            return action, None
        return action, _invoke_handler(handler, action)

    with ThreadPoolExecutor(max_workers=pool_workers, thread_name_prefix="arm-submit") as pool:
        results = list(pool.map(_run, group))

    for action, outcome in results:
        if outcome is None:
            summary.skipped += 1
            summary.decisions.append(replace(action, result="skipped-no-handler"))
        elif outcome.submitted:
            _count_success(summary, action.action)
            summary.decisions.append(replace(action, result="submitted"))
        elif outcome.skip_reason is not None:
            # HR-001/HR-004: handler asked to skip (e.g. ephemeral-OS-disk VM,
            # HA/replica rejection). Not a failure — do not count as failed and
            # do not trigger the OBS-004 repeated-failure alert (finding H3).
            summary.skipped += 1
            summary.decisions.append(
                replace(action, result=f"skipped:{outcome.skip_reason}",
                        warning=action.warning or outcome.skip_reason)
            )
        else:
            summary.failed += 1
            summary.decisions.append(replace(action, result="failed"))


def _record_skipped(ordering: OrderingResult, summary: CycleSummary) -> None:
    """Record safety-skipped (deny-listed / capped) items for the audit log."""
    for action in ordering.skipped:
        summary.decisions.append(replace(action, result=action.reason or "skipped"))
    summary.skipped += len(ordering.skipped)
    summary.cap_reached = ordering.cap_reached


def _invoke_handler(handler, action) -> "InvokeOutcome":
    """Invoke the handler start/stop once (no custom retry — M3).

    HTTP 429 throttling is retried by the Azure SDK's own retry policy
    (azure-core), so this does a single call. Returns an :class:`InvokeOutcome`:
    - ``submitted=True``        — the operation was submitted;
    - ``skip_reason=<reason>``  — the handler raised HandlerSkip (HR-001/HR-004):
      not a failure, must not be retried or alerted (H3);
    - neither                   — a genuine failure (counted as failed).
    """
    try:
        if action.action is ActionType.START:
            handler.start(action.resource)
        elif action.action is ActionType.STOP:
            handler.stop(action.resource)
        return InvokeOutcome(submitted=True)
    except Exception as exc:  # noqa: BLE001 — one failure must not abort the cycle
        reason = _handler_skip_reason(exc)
        if reason is not None:
            # HR-001/HR-004: explicit "skip, do not retry" signal (H3).
            logger.warning(
                "pwrsched.reconcile: skipping %s %s: %s",
                action.action.value, action.resource.resource_id, reason,
            )
            return InvokeOutcome(skip_reason=reason)
        logger.error(
            "pwrsched.reconcile: %s failed for %s: %s",
            action.action.value, action.resource.resource_id, exc,
        )
        return InvokeOutcome()


def _handler_skip_reason(exc: BaseException) -> Optional[str]:
    """Return the skip reason if ``exc`` is a handler HandlerSkip, else None.

    HandlerSkip is defined in ``handlers.base``. It is matched structurally (by
    class name and a ``reason`` attribute) so the engine does not import the
    handlers package, keeping the engine decoupled and SDK-free.
    """
    if type(exc).__name__ == "HandlerSkip":
        return getattr(exc, "reason", None) or (str(exc) or "handler-skip")
    return None


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
        selections, now=now, profile_provider=profile_provider, handlers=handlers,
        max_parallel_arm_calls=config.max_parallel_arm_calls,
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

    # --- Summary aggregate counts (SC-04, OBS-002) ---------------------------
    # Count desired-state and converged totals across ALL evaluated resources so
    # savings reporting works even when per-resource already-converged decision
    # records are suppressed (log_converged_decisions=False). "converged" counts
    # the no-op (already-converged) decisions; desiredRunning/desiredStopped
    # count by computed desired state regardless of action.
    for p in planned:
        if p.desired_state == DesiredState.RUNNING.value:
            summary.desired_running += 1
        elif p.desired_state == DesiredState.STOPPED.value:
            summary.desired_stopped += 1
        if p.action is ActionType.NONE and p.reason == "already-converged":
            summary.converged += 1

    # --- Telemetry (OBS-001/002/005) ----------------------------------------
    # One decision record per evaluated resource: the executed/skipped set is in
    # summary.decisions (with a result); the non-actionable set is logged with
    # its reason as the result. SC-04/NFR-011: when log_converged_decisions is
    # False, already-converged no-ops are suppressed (counted in the summary
    # only) so telemetry volume scales with actions, not resources. Every other
    # result — start, stop, skipped, excluded, failed, production-excluded — is
    # always emitted (OBS-001).
    for action in summary.decisions:
        if _is_suppressible_converged(action, config):
            continue
        telemetry.emit_decision(action, run_id=run_id, dry_run=config.dry_run)
    for action in non_actionable:
        if _is_suppressible_converged(action, config):
            continue
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
        converged=summary.converged,
        desired_running=summary.desired_running,
        desired_stopped=summary.desired_stopped,
    )

    logger.info(
        "pwrsched.summary: run=%s evaluated=%d started=%d stopped=%d skipped=%d "
        "failed=%d converged=%d cap=%s dur=%.3fs",
        summary.run_id, summary.evaluated, summary.started, summary.stopped,
        summary.skipped, summary.failed, summary.converged, summary.cap_reached,
        summary.duration_seconds,
    )
    return summary


def _is_suppressible_converged(action: PlannedAction, config: ReconcileConfig) -> bool:
    """True when this is an ``already-converged`` no-op and logging them is off (SC-04)."""
    return (
        not config.log_converged_decisions
        and action.action is ActionType.NONE
        and action.reason == "already-converged"
    )
