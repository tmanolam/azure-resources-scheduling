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
from engine.models import ActionType, ResourceRecord  # noqa: E402
from engine.reconcile import (  # noqa: E402
    ReconcileConfig,
    RetryableThrottling,
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


class ThrottleHandler(FakeHandler):
    def __init__(self, state, fail_times, retry_after=0.0):
        super().__init__(state)
        self.fail_times = fail_times
        self.retry_after = retry_after
        self.start_attempts = 0

    def start(self, resource):
        self.start_attempts += 1
        if self.start_attempts <= self.fail_times:
            raise RetryableThrottling(self.retry_after)
        self.started.append(resource.resource_id)


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


# --- NFR-005 throttling back-off ---------------------------------------------

def test_throttle_retries_then_succeeds():
    sleeps = []
    h = ThrottleHandler("Stopped", fail_times=2, retry_after=0.5)
    summary = run_reconcile([_sel("vm1")], now=_monday_10am(), run_id="r1",
                            profile_provider=_profiles, handlers={"vm": h},
                            config=ReconcileConfig(dry_run=False, max_throttle_retries=3),
                            sleep=sleeps.append)
    assert h.started == ["vm1"]
    assert h.start_attempts == 3           # 2 throttles + 1 success
    assert sleeps == [0.5, 0.5]            # backed off twice
    assert summary.started == 1


def test_throttle_exhausts_retries_marks_failed():
    sleeps = []
    h = ThrottleHandler("Stopped", fail_times=5, retry_after=0.0)
    summary = run_reconcile([_sel("vm1")], now=_monday_10am(), run_id="r1",
                            profile_provider=_profiles, handlers={"vm": h},
                            config=ReconcileConfig(dry_run=False, max_throttle_retries=2),
                            sleep=sleeps.append)
    assert h.started == []
    assert summary.failed == 1


# --- ordering integration: db starts before app ------------------------------

def test_start_ordering_db_before_app():
    db = FakeHandler("Stopped")
    aks = FakeHandler("Stopped")
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
