"""Unit tests for the reconciliation orchestrator (T-204)."""

from __future__ import annotations

import datetime as _dt
import os
import sys
from zoneinfo import ZoneInfo

_SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from engine.evaluator import parse_profile  # noqa: E402
from engine.models import ResourceRecord  # noqa: E402
from engine.reconcile import (  # noqa: E402
    ReconcileConfig,
    run_reconcile,
)
from engine.selection import SelectionResult  # noqa: E402

BKK = ZoneInfo("Asia/Bangkok")
UTC = _dt.timezone.utc

PROFILE = parse_profile("weekday-0830-1730", {
    "timezone": "Asia/Bangkok",
    "runWindows": [{"days": ["Mon", "Tue", "Wed", "Thu", "Fri"], "start": "08:30", "stop": "17:30"}],
    "startOffsetMinutesByOrder": {"1": -30, "2": -15, "3": 0},
})


def _profiles(name):
    return PROFILE if name == "weekday-0830-1730" else None


def _rec(rid, handler="vm", rtype="Microsoft.Compute/virtualMachines", sub="s1"):
    return ResourceRecord(resource_id=rid, resource_type=rtype, handler_key=handler,
                          subscription_id=sub, resource_group="rg1")


def _sel(rid, handler="vm", order=3, override_state=None, override_until=None, eligible=True,
         reason="eligible", profile="weekday-0830-1730"):
    return SelectionResult(_rec(rid, handler), eligible, reason, profile, order,
                           override_state, override_until)


class FakeHandler:
    def __init__(self, state):
        self.state = state
        self.started = []
        self.stopped = []

    def get_state(self, resource):
        return self.state

    def start(self, resource):
        self.started.append(resource.resource_id)

    def stop(self, resource):
        self.stopped.append(resource.resource_id)


def _monday_10am():
    return _dt.datetime(2026, 10, 5, 10, 0, tzinfo=BKK).astimezone(UTC)


def _friday_6pm():
    return _dt.datetime(2026, 10, 9, 18, 0, tzinfo=BKK).astimezone(UTC)


# --- FR-004 idempotency ------------------------------------------------------

def test_no_action_when_already_running():
    h = FakeHandler("Running")
    summary = run_reconcile([_sel("vm1")], now=_monday_10am(), run_id="r1",
                            profile_provider=_profiles, handlers={"vm": h},
                            config=ReconcileConfig(dry_run=False))
    assert h.started == [] and h.stopped == []
    assert summary.started == 0 and summary.stopped == 0


def test_start_when_running_desired_but_stopped():
    h = FakeHandler("Stopped")
    summary = run_reconcile([_sel("vm1")], now=_monday_10am(), run_id="r1",
                            profile_provider=_profiles, handlers={"vm": h},
                            config=ReconcileConfig(dry_run=False))
    assert h.started == ["vm1"]
    assert summary.started == 1


def test_stop_when_stopped_desired_but_running():
    h = FakeHandler("Running")
    summary = run_reconcile([_sel("vm1")], now=_friday_6pm(), run_id="r1",
                            profile_provider=_profiles, handlers={"vm": h},
                            config=ReconcileConfig(dry_run=False))
    assert h.stopped == ["vm1"]
    assert summary.stopped == 1


# --- FR-030 dry-run ----------------------------------------------------------

def test_dry_run_submits_nothing_but_counts():
    h = FakeHandler("Stopped")
    summary = run_reconcile([_sel("vm1")], now=_monday_10am(), run_id="r1",
                            profile_provider=_profiles, handlers={"vm": h},
                            config=ReconcileConfig(dry_run=True))
    assert h.started == []            # no real call
    assert summary.started == 1       # intent counted


# --- FR-033 transitional / unknown skip --------------------------------------

def test_transitional_state_skipped():
    h = FakeHandler("Starting")
    summary = run_reconcile([_sel("vm1")], now=_monday_10am(), run_id="r1",
                            profile_provider=_profiles, handlers={"vm": h},
                            config=ReconcileConfig(dry_run=False))
    assert h.started == [] and summary.skipped >= 1


def test_unknown_state_skipped():
    h = FakeHandler("WhoKnows")
    summary = run_reconcile([_sel("vm1")], now=_monday_10am(), run_id="r1",
                            profile_provider=_profiles, handlers={"vm": h},
                            config=ReconcileConfig(dry_run=False))
    assert h.started == [] and summary.skipped >= 1


# --- ineligible / unknown profile --------------------------------------------

def test_ineligible_selection_counted_skipped():
    h = FakeHandler("Running")
    summary = run_reconcile([_sel("vm1", eligible=False, reason="production-excluded")],
                            now=_monday_10am(), run_id="r1",
                            profile_provider=_profiles, handlers={"vm": h},
                            config=ReconcileConfig(dry_run=False))
    assert summary.skipped >= 1 and summary.started == 0


# --- NFR-005 throttling: handled by azure-core retry (M3), no engine back-off --

def test_no_custom_throttle_mechanism_in_config():
    # M3: the engine no longer exposes a custom throttle retry knob; HTTP 429 is
    # retried by the Azure SDK's own policy (configured in runtime).
    cfg = ReconcileConfig()
    assert not hasattr(cfg, "max_throttle_retries")


# --- ordering integration: db starts before app ------------------------------

def test_start_ordering_db_before_app():
    order_log = []

    class Logging(FakeHandler):
        def __init__(self, state, label):
            super().__init__(state)
            self.label = label

        def start(self, resource):
            order_log.append(self.label)
            super().start(resource)

    dbh = Logging("Stopped", "db")
    aksh = Logging("Stopped", "aks")
    # 08:00 Bangkok: order1 (db, offset -30) running; order2 (aks, offset -15) not yet.
    at_0800 = _dt.datetime(2026, 10, 5, 8, 0, tzinfo=BKK).astimezone(UTC)
    sels = [
        _sel("aks1", handler="aks", order=2),
        _sel("db1", handler="postgres-flex", order=1),
    ]
    summary = run_reconcile(sels, now=at_0800, run_id="r1", profile_provider=_profiles,
                            handlers={"aks": aksh, "postgres-flex": dbh},
                            config=ReconcileConfig(dry_run=False))
    assert dbh.started == ["db1"]
    assert aksh.started == []       # aks offset -15 => starts 08:15, not yet at 08:00
    assert summary.started == 1


# --- H3: HandlerSkip is counted as skipped, not failed -----------------------

class _Skip(Exception):
    """Mimics handlers.base.HandlerSkip (matched structurally by the engine)."""

    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


# Give it the exact class name the engine matches on.
_Skip.__name__ = "HandlerSkip"


class SkipHandler(FakeHandler):
    def __init__(self, state, reason):
        super().__init__(state)
        self.reason = reason

    def start(self, resource):
        raise _Skip(self.reason)

    def stop(self, resource):
        raise _Skip(self.reason)


def test_handler_skip_counts_as_skipped_not_failed():
    # H3: desired Stopped (Fri 18:00) + running => stop; handler raises skip.
    h = SkipHandler("Running", "vm-ephemeral-os-disk-unsupported")
    summary = run_reconcile([_sel("vm1")], now=_friday_6pm(), run_id="r1",
                            profile_provider=_profiles, handlers={"vm": h},
                            config=ReconcileConfig(dry_run=False))
    assert summary.failed == 0
    assert summary.skipped >= 1
    results = [d.result for d in summary.decisions]
    assert any(r == "skipped:vm-ephemeral-os-disk-unsupported" for r in results)


def test_handler_skip_not_retried():
    # The skip path must not loop/retry (unlike throttling back-off).
    attempts = {"n": 0}

    class CountingSkip(FakeHandler):
        def stop(self, resource):
            attempts["n"] += 1
            raise _Skip("sqlmi-operation-rejected")

    h = CountingSkip("Running")
    run_reconcile([_sel("mi1", handler="sqlmi", order=1)], now=_friday_6pm(), run_id="r1",
                  profile_provider=_profiles, handlers={"sqlmi": h},
                  config=ReconcileConfig(dry_run=False))
    assert attempts["n"] == 1  # called once, no retry


# --- H4: powered-off (stopped-allocated) VMs are deallocated -----------------

def test_stopped_allocated_vm_is_deallocated_when_desired_stopped():
    # Fri 18:00 => desired Stopped. VM reports stopped-but-allocated => STOP.
    h = FakeHandler("stopped-allocated")
    summary = run_reconcile([_sel("vm1")], now=_friday_6pm(), run_id="r1",
                            profile_provider=_profiles, handlers={"vm": h},
                            config=ReconcileConfig(dry_run=False))
    assert h.stopped == ["vm1"]      # deallocate submitted (H4)
    assert summary.stopped == 1


def test_stopped_allocated_vm_is_started_when_desired_running():
    # Mon 10:00 => desired Running. A stopped-allocated VM must be started.
    h = FakeHandler("stopped-allocated")
    summary = run_reconcile([_sel("vm1")], now=_monday_10am(), run_id="r1",
                            profile_provider=_profiles, handlers={"vm": h},
                            config=ReconcileConfig(dry_run=False))
    assert h.started == ["vm1"]
    assert summary.started == 1


def test_truly_deallocated_vm_is_converged_when_desired_stopped():
    # A genuinely deallocated VM at Fri 18:00 (desired Stopped) needs no action.
    h = FakeHandler("deallocated")
    summary = run_reconcile([_sel("vm1")], now=_friday_6pm(), run_id="r1",
                            profile_provider=_profiles, handlers={"vm": h},
                            config=ReconcileConfig(dry_run=False))
    assert h.stopped == [] and summary.stopped == 0


# --- M1: planning uses Resource Graph power state, no per-resource ARM read ---

def test_plan_uses_resource_graph_power_state_without_get_state():
    # Record carries power_state from discovery; handler.get_state must NOT be
    # called during planning (M1: avoids per-resource ARM reads at scale).
    calls = {"get_state": 0}

    class NoReadHandler(FakeHandler):
        def get_state(self, resource):
            calls["get_state"] += 1
            raise AssertionError("get_state must not be called when power_state is present")

    rec = ResourceRecord("/vm1", "Microsoft.Compute/virtualMachines", "vm", "s1", "rg1",
                         power_state="running")
    sel = SelectionResult(rec, True, "eligible", "weekday-0830-1730", 3, None, None)
    # Fri 18:00 desired Stopped; running => stop submitted, using RG state only.
    summary = run_reconcile([sel], now=_friday_6pm(), run_id="r1",
                            profile_provider=_profiles, handlers={"vm": NoReadHandler("ignored")},
                            config=ReconcileConfig(dry_run=False))
    assert calls["get_state"] == 0
    assert summary.stopped == 1


def test_plan_falls_back_to_get_state_when_power_state_absent():
    rec = ResourceRecord("/vm1", "Microsoft.Compute/virtualMachines", "vm", "s1", "rg1")  # no power_state
    sel = SelectionResult(rec, True, "eligible", "weekday-0830-1730", 3, None, None)
    h = FakeHandler("Running")
    summary = run_reconcile([sel], now=_friday_6pm(), run_id="r1",
                            profile_provider=_profiles, handlers={"vm": h},
                            config=ReconcileConfig(dry_run=False))
    assert summary.stopped == 1  # fell back to handler.get_state


def test_plan_rg_stopped_vm_is_deallocated():
    # M1 + H4: a VM whose RG power state is 'stopped' (billed) is deallocated.
    rec = ResourceRecord("/vm1", "Microsoft.Compute/virtualMachines", "vm", "s1", "rg1",
                         power_state="stopped")
    sel = SelectionResult(rec, True, "eligible", "weekday-0830-1730", 3, None, None)
    h = FakeHandler("ignored")
    summary = run_reconcile([sel], now=_friday_6pm(), run_id="r1",
                            profile_provider=_profiles, handlers={"vm": h},
                            config=ReconcileConfig(dry_run=False))
    assert h.stopped == ["/vm1"] and summary.stopped == 1


# --- N7: fallback get_state reads use a bounded thread pool ------------------

def test_fallback_reads_run_concurrently_bounded_by_config():
    # N7: resources without a Resource Graph power state need an ARM get_state;
    # those reads must run concurrently (bounded by max_parallel_arm_calls), not
    # one-by-one. We observe concurrency with a barrier-like counter.
    import threading

    max_parallel = 4
    n = 8
    lock = threading.Lock()
    state = {"active": 0, "peak": 0}

    class SlowHandler(FakeHandler):
        def get_state(self, resource):
            with lock:
                state["active"] += 1
                state["peak"] = max(state["peak"], state["active"])
            # Spin briefly so overlapping reads actually coincide.
            import time as _t
            _t.sleep(0.02)
            with lock:
                state["active"] -= 1
            return "Running"

    h = SlowHandler("Running")
    sels = [_sel(f"vm{i}") for i in range(n)]  # _rec has no power_state => fallback
    summary = run_reconcile(sels, now=_friday_6pm(), run_id="r1",
                            profile_provider=_profiles, handlers={"vm": h},
                            config=ReconcileConfig(dry_run=False, max_parallel_arm_calls=max_parallel))
    # Fri 18:00 desired Stopped; all running => all stopped.
    assert summary.stopped == n
    # Concurrency was used, and never exceeded the configured bound.
    assert state["peak"] > 1
    assert state["peak"] <= max_parallel


def test_fallback_read_failure_is_state_read_failed():
    # N7: a get_state that raises during the prefetch must yield a logged
    # 'state-read-failed' decision, not abort the cycle or raise.
    from engine.models import ActionType
    from engine.reconcile import plan_actions

    class BoomHandler(FakeHandler):
        def get_state(self, resource):
            raise RuntimeError("ARM read failed")

    planned = plan_actions([_sel("vm1")], now=_friday_6pm(), profile_provider=_profiles,
                           handlers={"vm": BoomHandler("x")})
    assert len(planned) == 1
    assert planned[0].action is ActionType.NONE
    assert planned[0].reason == "state-read-failed"


def test_fallback_handler_skip_is_logged_skip_not_failed():
    # V3/HR-008: get_state raising HandlerSkip during the prefetch (e.g. a
    # Flexible scale set) must be logged as skip:<reason>, not state-read-failed,
    # and must not count as a failure.
    from engine.models import ActionType
    from engine.reconcile import plan_actions

    class SkipStateHandler(FakeHandler):
        def get_state(self, resource):
            raise _Skip("vmss-flexible-unsupported")

    planned = plan_actions([_sel("ss1", handler="vmss")], now=_friday_6pm(),
                           profile_provider=_profiles,
                           handlers={"vmss": SkipStateHandler("x")})
    assert len(planned) == 1
    assert planned[0].action is ActionType.NONE
    assert planned[0].reason == "skip:vmss-flexible-unsupported"


def test_fallback_handler_skip_summary_not_failed():
    # The same skip through the full run_reconcile: failed == 0 and the resource
    # is counted as skipped (non-actionable). The skip:<reason> is carried on the
    # planned action's reason and emitted by telemetry (emit_decision uses
    # action.reason as the result for non-actionable decisions).
    class SkipStateHandler(FakeHandler):
        def get_state(self, resource):
            raise _Skip("vmss-flexible-unsupported")

    summary = run_reconcile([_sel("ss1", handler="vmss")], now=_friday_6pm(), run_id="r1",
                            profile_provider=_profiles,
                            handlers={"vmss": SkipStateHandler("x")},
                            config=ReconcileConfig(dry_run=True))
    assert summary.failed == 0
    assert summary.evaluated == 1
    assert summary.skipped >= 1
