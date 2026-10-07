"""Large-tenant scaling tests (SC-01, SC-04, SC-05).

Covers the scaling workstream (REQUIREMENTS §10.1, D-09 option A — single
``maxActionsPerRun``):

* SC-01 (FR-034) — parallel action submission through a bounded thread pool,
  per order group with a barrier between groups; failures isolated; dry-run
  unchanged (sequential, no ARM calls).
* SC-04 (NFR-011) — ``logConvergedDecisions`` suppresses per-resource
  already-converged decision records; the summary still carries
  ``converged`` / ``desiredRunning`` / ``desiredStopped``.
* SC-05 (NFR-002) — a 5,000-resource load with a large peak transition and
  simulated latency completes well within the time budget, the single cap
  defers the excess (``capReached``), and order groups are respected.
"""

from __future__ import annotations

import datetime as _dt
import os
import sys
import threading
import time as _time
from zoneinfo import ZoneInfo

_SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from engine import telemetry  # noqa: E402
from engine.evaluator import parse_profile  # noqa: E402
from engine.models import ActionType, PlannedAction, ResourceRecord  # noqa: E402
from engine.ordering import order_and_limit_actions  # noqa: E402
from engine.reconcile import (  # noqa: E402
    CycleSummary,
    ReconcileConfig,
    execute_actions,
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


def _friday_6pm():
    return _dt.datetime(2026, 10, 9, 18, 0, tzinfo=BKK).astimezone(UTC)


def _monday_10am():
    return _dt.datetime(2026, 10, 5, 10, 0, tzinfo=BKK).astimezone(UTC)


def _rec(rid, handler="vm", rtype="Microsoft.Compute/virtualMachines", sub="s1", power_state="running"):
    # Give records a Resource Graph power_state so planning needs no fallback
    # read — the load test then isolates submission throughput (SC-01/SC-05).
    return ResourceRecord(resource_id=rid, resource_type=rtype, handler_key=handler,
                          subscription_id=sub, resource_group="rg1", power_state=power_state)


def _sel(rid, handler="vm", order=3, power_state="running", eligible=True,
         reason="eligible", profile="weekday-0830-1730"):
    return SelectionResult(_rec(rid, handler, power_state=power_state), eligible, reason,
                           profile, order, None, None)


def _planned_stop(rid, order=3):
    return PlannedAction(_rec(rid), ActionType.STOP, "Stopped", "stop",
                         "weekday-0830-1730", order, None, "Running")


# ===========================================================================
# SC-01 — parallel action submission
# ===========================================================================

class _ConcurrencyHandler:
    """Records peak concurrency across start/stop submissions."""

    def __init__(self, latency=0.01):
        self.latency = latency
        self._lock = threading.Lock()
        self.active = 0
        self.peak = 0
        self.started: list[str] = []
        self.stopped: list[str] = []

    def _work(self, bucket, rid):
        with self._lock:
            self.active += 1
            self.peak = max(self.peak, self.active)
        _time.sleep(self.latency)
        with self._lock:
            self.active -= 1
            bucket.append(rid)

    def get_state(self, resource):
        return "Running"

    def start(self, resource):
        self._work(self.started, resource.resource_id)

    def stop(self, resource):
        self._work(self.stopped, resource.resource_id)


def test_sc01_submission_concurrency_bounded():
    """Concurrency never exceeds max_parallel_actions, and parallelism is used."""
    bound = 5
    n = 40
    h = _ConcurrencyHandler(latency=0.01)
    sels = [_sel(f"vm{i}") for i in range(n)]  # all order 3 => one stop group at 18:00
    summary = run_reconcile(sels, now=_friday_6pm(), run_id="r1",
                            profile_provider=_profiles, handlers={"vm": h},
                            config=ReconcileConfig(dry_run=False, max_parallel_actions=bound))
    assert summary.stopped == n
    assert h.peak > 1              # parallelism actually happened
    assert h.peak <= bound         # never exceeded the configured bound


def test_sc01_order_group_barrier():
    """All order-N submissions complete before order-(N±1) begins (FR-006).

    At 18:00 Bangkok the standard profile stops everything; stops run descending
    by order (3 then 2 then 1). A later group must never begin while an earlier
    group is still in flight.
    """
    events_lock = threading.Lock()
    first_start: dict[int, float] = {}
    last_finish: dict[int, float] = {}

    class OrderHandler:
        def get_state(self, resource):
            return "Running"

        def start(self, resource):  # not used at 18:00
            raise AssertionError("no starts at 18:00")

        def stop(self, resource):
            order = int(resource.resource_group.split("-")[-1])  # encode order in rg
            now = _time.perf_counter()
            with events_lock:
                prev = first_start.get(order)
                first_start[order] = now if prev is None else min(prev, now)
            _time.sleep(0.01)
            with events_lock:
                last_finish[order] = max(last_finish.get(order, 0.0), _time.perf_counter())

    def _sel_order(rid, order):
        rec = ResourceRecord(rid, "Microsoft.Compute/virtualMachines", "vm", "s1",
                             f"rg-{order}", power_state="running")
        return SelectionResult(rec, True, "eligible", "weekday-0830-1730", order, None, None)

    sels = []
    for order in (1, 2, 3):
        for i in range(6):
            sels.append(_sel_order(f"o{order}-{i}", order))

    run_reconcile(sels, now=_friday_6pm(), run_id="r1", profile_provider=_profiles,
                  handlers={"vm": OrderHandler()},
                  config=ReconcileConfig(dry_run=False, max_parallel_actions=4))

    # Stops run order 3, then 2, then 1 (descending). The barrier means group 3
    # fully finishes before group 2 starts, and group 2 before group 1.
    assert last_finish[3] <= first_start[2] + 1e-6
    assert last_finish[2] <= first_start[1] + 1e-6


def test_sc01_one_failure_does_not_stop_the_group():
    """A single failing submission is isolated; the rest of the group proceeds."""
    class FlakyHandler:
        def get_state(self, resource):
            return "Running"

        def start(self, resource):
            pass

        def stop(self, resource):
            if resource.resource_id == "vm-bad":
                raise RuntimeError("ARM 500")

    sels = [_sel("vm-a"), _sel("vm-bad"), _sel("vm-c")]
    summary = run_reconcile(sels, now=_friday_6pm(), run_id="r1",
                            profile_provider=_profiles, handlers={"vm": FlakyHandler()},
                            config=ReconcileConfig(dry_run=False, max_parallel_actions=3))
    assert summary.failed == 1
    assert summary.stopped == 2          # the other two still submitted
    results = sorted(d.result for d in summary.decisions)
    assert results.count("submitted") == 2
    assert results.count("failed") == 1


def test_sc01_dry_run_is_sequential_no_calls():
    """Dry-run makes no ARM calls and still counts intent (unchanged path)."""
    h = _ConcurrencyHandler(latency=0.0)
    sels = [_sel(f"vm{i}") for i in range(10)]
    summary = run_reconcile(sels, now=_friday_6pm(), run_id="r1",
                            profile_provider=_profiles, handlers={"vm": h},
                            config=ReconcileConfig(dry_run=True, max_parallel_actions=10))
    assert h.stopped == [] and h.started == []   # no real submissions
    assert summary.stopped == 10                 # intent counted
    assert h.peak == 0                           # handler work never ran


def test_sc01_cap_applied_before_parallel_submission():
    """The single cap (D-09) truncates the ordered list before submission."""
    h = _ConcurrencyHandler(latency=0.0)
    n = 50
    cap = 10
    sels = [_sel(f"vm{i}") for i in range(n)]
    summary = run_reconcile(sels, now=_friday_6pm(), run_id="r1",
                            profile_provider=_profiles, handlers={"vm": h},
                            config=ReconcileConfig(dry_run=False, max_actions_per_run=cap,
                                                   max_parallel_actions=10))
    assert len(h.stopped) == cap          # only the cap's worth were submitted
    assert summary.stopped == cap
    assert summary.cap_reached is True


# ===========================================================================
# SC-04 — telemetry volume
# ===========================================================================

def _capture_events(monkeypatch):
    """Capture emit_decision / emit_summary calls on the telemetry module."""
    decisions: list = []
    summaries: list = []

    def _dec(action, *, run_id, dry_run):
        decisions.append(action)

    def _sum(**kwargs):
        summaries.append(kwargs)

    monkeypatch.setattr(telemetry, "emit_decision", _dec)
    monkeypatch.setattr(telemetry, "emit_summary", _sum)
    return decisions, summaries


class _RunningHandler:
    def get_state(self, resource):
        return "Running"

    def start(self, resource):
        pass

    def stop(self, resource):
        pass


def test_sc04_converged_suppressed_when_disabled(monkeypatch):
    decisions, summaries = _capture_events(monkeypatch)
    # Monday 10:00 => desired Running; already-running resources are converged.
    sels = [_sel(f"vm{i}", power_state="running") for i in range(5)]
    run_reconcile(sels, now=_monday_10am(), run_id="r1", profile_provider=_profiles,
                  handlers={"vm": _RunningHandler()},
                  config=ReconcileConfig(dry_run=False, log_converged_decisions=False))
    # No per-resource decision records for the converged no-ops.
    assert decisions == []
    # But the summary still reports the converged count.
    assert summaries and summaries[0]["converged"] == 5
    assert summaries[0]["desired_running"] == 5


def test_sc04_converged_logged_by_default(monkeypatch):
    decisions, summaries = _capture_events(monkeypatch)
    sels = [_sel(f"vm{i}", power_state="running") for i in range(5)]
    run_reconcile(sels, now=_monday_10am(), run_id="r1", profile_provider=_profiles,
                  handlers={"vm": _RunningHandler()},
                  config=ReconcileConfig(dry_run=False, log_converged_decisions=True))
    # Default True => every converged resource still gets a decision record.
    assert len(decisions) == 5
    assert summaries[0]["converged"] == 5


def test_sc04_non_converged_always_logged_even_when_disabled(monkeypatch):
    """Start/stop/skip/excluded/failed are always logged; only no-ops suppressed."""
    decisions, _ = _capture_events(monkeypatch)
    # Friday 18:00 => desired Stopped. Mix: one running (=> stop, logged), one
    # already deallocated (=> converged, suppressed), one excluded (logged).
    sels = [
        _sel("vm-run", power_state="running"),
        _sel("vm-conv", power_state="deallocated"),
        _sel("vm-excl", power_state="running", eligible=False, reason="production-excluded"),
    ]
    run_reconcile(sels, now=_friday_6pm(), run_id="r1", profile_provider=_profiles,
                  handlers={"vm": _RunningHandler()},
                  config=ReconcileConfig(dry_run=False, log_converged_decisions=False))
    logged = {d.resource.resource_id: d.result for d in decisions}
    assert "vm-run" in logged                 # the stop is logged
    assert "vm-excl" in logged                # the exclusion is logged
    assert "vm-conv" not in logged            # only the no-op is suppressed


def test_sc04_summary_counts_consistent_across_modes():
    """desiredRunning/desiredStopped/converged are identical regardless of logging mode."""
    sels = [_sel(f"vm{i}", power_state="running") for i in range(4)]
    s_on = run_reconcile(sels, now=_monday_10am(), run_id="a", profile_provider=_profiles,
                         handlers={"vm": _RunningHandler()},
                         config=ReconcileConfig(dry_run=True, log_converged_decisions=True))
    s_off = run_reconcile(sels, now=_monday_10am(), run_id="b", profile_provider=_profiles,
                          handlers={"vm": _RunningHandler()},
                          config=ReconcileConfig(dry_run=True, log_converged_decisions=False))
    assert s_on.converged == s_off.converged == 4
    assert s_on.desired_running == s_off.desired_running == 4
    assert s_on.desired_stopped == s_off.desired_stopped == 0


def test_sc04_emit_summary_carries_new_fields(monkeypatch):
    """telemetry.emit_summary receives the three new counts."""
    _, summaries = _capture_events(monkeypatch)
    run_reconcile([_sel("vm1", power_state="running")], now=_friday_6pm(), run_id="r1",
                  profile_provider=_profiles, handlers={"vm": _RunningHandler()},
                  config=ReconcileConfig(dry_run=True))
    assert summaries
    for key in ("converged", "desired_running", "desired_stopped"):
        assert key in summaries[0]


# ===========================================================================
# SC-05 — load test (NFR-002)
# ===========================================================================

def test_sc05_load_5000_resources_within_budget():
    """5,000 resources, ~4,000-resource peak stop, simulated latency.

    Asserts the cap defers the excess, capReached is set, bounded parallelism is
    used, no unhandled exceptions, and the cycle finishes well within the
    10-minute NFR-002 budget. Latency is scaled down (2 ms) so the test is fast
    while still exercising the bounded parallel submitter.
    """
    total = 5000
    running = 4000            # peak transition: 4,000 running => want Stopped at 18:00
    cap = 500
    bound = 20
    latency = 0.002

    # Mix of orders (1 db, 2 aks, 3 vm) so there are multiple order groups.
    sels = []
    for i in range(total):
        order = (i % 3) + 1
        handler = {1: "postgres-flex", 2: "aks", 3: "vm"}[order]
        rtype = {1: "Microsoft.DBforPostgreSQL/flexibleServers",
                 2: "Microsoft.ContainerService/managedClusters",
                 3: "Microsoft.Compute/virtualMachines"}[order]
        power = "running" if i < running else "deallocated"
        rec = ResourceRecord(f"/r{i}", rtype, handler, "s1", "rg1", power_state=power)
        sels.append(SelectionResult(rec, True, "eligible", "weekday-0830-1730", order, None, None))

    lock = threading.Lock()
    counters = {"submitted": 0, "active": 0, "peak": 0}

    class LoadHandler:
        def get_state(self, resource):
            return "Running"

        def _work(self):
            with lock:
                counters["active"] += 1
                counters["peak"] = max(counters["peak"], counters["active"])
            _time.sleep(latency)
            with lock:
                counters["active"] -= 1
                counters["submitted"] += 1

        def start(self, resource):
            self._work()

        def stop(self, resource):
            self._work()

    handlers = {"vm": LoadHandler(), "aks": LoadHandler(), "postgres-flex": LoadHandler()}

    t0 = _time.monotonic()
    summary = run_reconcile(sels, now=_friday_6pm(), run_id="load",
                            profile_provider=_profiles, handlers=handlers,
                            config=ReconcileConfig(dry_run=False, max_actions_per_run=cap,
                                                   max_parallel_actions=bound))
    elapsed = _time.monotonic() - t0

    # NFR-002: well within the 10-minute budget (generous ceiling for CI).
    assert elapsed < 60
    # Single cap (D-09) deferred the excess beyond `cap`.
    assert summary.stopped == cap
    assert summary.cap_reached is True
    assert counters["submitted"] == cap
    # Bounded parallelism was used and never exceeded the bound.
    assert counters["peak"] > 1
    assert counters["peak"] <= bound
    # No failures, and the summary saw all 5,000 resources.
    assert summary.failed == 0
    assert summary.evaluated == total


def test_sc05_cap_zero_defers_everything():
    """A cap of 0 submits nothing and flags capReached (defensive bound)."""
    sels = [_sel(f"vm{i}") for i in range(5)]

    class H:
        def get_state(self, resource):
            return "Running"

        def start(self, resource):
            raise AssertionError("nothing should be submitted at cap 0")

        def stop(self, resource):
            raise AssertionError("nothing should be submitted at cap 0")

    summary = run_reconcile(sels, now=_friday_6pm(), run_id="r1", profile_provider=_profiles,
                            handlers={"vm": H()},
                            config=ReconcileConfig(dry_run=False, max_actions_per_run=0,
                                                   max_parallel_actions=10))
    assert summary.stopped == 0
    assert summary.cap_reached is True


# --- direct execute_actions grouping check (unit level) ----------------------

def test_execute_actions_submits_every_item_once():
    """execute_actions over a pre-ordered, pre-capped list submits every item once."""
    actions = [_planned_stop(f"s{i}", order=3) for i in range(4)]
    actions += [_planned_stop(f"d{i}", order=1) for i in range(2)]
    ordering = order_and_limit_actions(actions, max_actions_per_run=100)

    class H:
        def __init__(self):
            self.calls = []
            self._lock = threading.Lock()

        def get_state(self, resource):
            return "Running"

        def start(self, resource):
            with self._lock:
                self.calls.append(resource.resource_id)

        def stop(self, resource):
            with self._lock:
                self.calls.append(resource.resource_id)

    h = H()
    summary = CycleSummary(run_id="r1")
    execute_actions(ordering, handlers={"vm": h}, config=ReconcileConfig(dry_run=False),
                    summary=summary)
    assert sorted(h.calls) == sorted([f"s{i}" for i in range(4)] + [f"d{i}" for i in range(2)])
    assert summary.stopped == 6
