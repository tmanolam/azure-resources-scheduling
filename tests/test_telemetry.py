"""Unit tests for structured telemetry (T-501) and its reconcile wiring,
verifying the field contract the alert KQL (T-502) depends on."""

from __future__ import annotations

import datetime as _dt
import logging
import os
import sys
from zoneinfo import ZoneInfo

import pytest

_SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from engine import telemetry  # noqa: E402
from engine.evaluator import parse_profile  # noqa: E402
from engine.models import ActionType, PlannedAction, ResourceRecord  # noqa: E402
from engine.reconcile import ReconcileConfig, RetryableThrottling, run_reconcile  # noqa: E402
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


def _rec(rid, handler="vm", rtype="Microsoft.Compute/virtualMachines"):
    return ResourceRecord(resource_id=rid, resource_type=rtype, handler_key=handler,
                          subscription_id="s1", resource_group="rg1")


def _sel(rid, handler="vm", order=3, eligible=True, reason="eligible", profile="weekday-0830-1730"):
    return SelectionResult(_rec(rid, handler), eligible, reason, profile, order, None, None)


class FakeHandler:
    def __init__(self, state):
        self.state = state

    def get_state(self, resource):
        return self.state

    def start(self, resource):
        pass

    def stop(self, resource):
        pass


class FailHandler(FakeHandler):
    def start(self, resource):
        raise RuntimeError("boom")

    def stop(self, resource):
        raise RuntimeError("boom")


@pytest.fixture
def captured(caplog):
    caplog.set_level(logging.INFO, logger="pwrsched.telemetry")
    return caplog


def _dims(records, event):
    """Return list of custom_dimensions dicts for a given event."""
    out = []
    for r in records:
        cd = getattr(r, "custom_dimensions", None)
        if cd and cd.get("event") == event:
            out.append(cd)
    return out


def _monday_10am():
    return _dt.datetime(2026, 10, 5, 10, 0, tzinfo=BKK).astimezone(UTC)


# --- emit_* unit-level --------------------------------------------------------

def test_emit_decision_fields(captured):
    action = PlannedAction(
        _rec("/vm1"), ActionType.START, "Running", "in-run-window",
        profile_name="weekday-0830-1730", order=3, actual_state="Stopped", result="submitted",
    )
    telemetry.emit_decision(action, run_id="r1", dry_run=False)
    d = _dims(captured.records, telemetry.DECISION_EVENT)
    assert len(d) == 1
    cd = d[0]
    # Field contract required by README query + OBS-001.
    for key in ["event", "runId", "resourceId", "type", "profile", "desiredState",
                "actualState", "action", "dryRun", "result"]:
        assert key in cd, f"missing {key}"
    assert cd["resourceId"] == "/vm1"
    assert cd["desiredState"] == "Running"
    assert cd["actualState"] == "Stopped"
    assert cd["action"] == "start"
    assert cd["result"] == "submitted"
    assert cd["dryRun"] is False


def test_emit_summary_fields(captured):
    telemetry.emit_summary(run_id="r1", evaluated=5, started=2, stopped=1,
                           skipped=1, failed=1, cap_reached=False, duration_seconds=0.123)
    d = _dims(captured.records, telemetry.SUMMARY_EVENT)
    assert len(d) == 1
    cd = d[0]
    for key in ["event", "runId", "evaluated", "started", "stopped", "skipped",
                "failed", "capReached", "durationSeconds"]:
        assert key in cd
    assert cd["evaluated"] == 5 and cd["failed"] == 1


def test_emit_cap_reached_fields(captured):
    telemetry.emit_cap_reached(run_id="r1", cap=200, deferred=3)
    d = _dims(captured.records, telemetry.CAP_REACHED_EVENT)
    assert len(d) == 1
    assert d[0]["cap"] == 200 and d[0]["deferred"] == 3


# --- reconcile wiring --------------------------------------------------------

def test_run_reconcile_emits_decision_and_summary(captured):
    h = FakeHandler("Stopped")  # desired Running (Mon 10am) => start
    run_reconcile([_sel("/vm1")], now=_monday_10am(), run_id="run-xyz",
                  profile_provider=_profiles, handlers={"vm": h},
                  config=ReconcileConfig(dry_run=True))
    decisions = _dims(captured.records, telemetry.DECISION_EVENT)
    summaries = _dims(captured.records, telemetry.SUMMARY_EVENT)
    assert len(summaries) == 1
    assert summaries[0]["runId"] == "run-xyz"
    assert len(decisions) == 1
    assert decisions[0]["action"] == "start"
    assert decisions[0]["result"] == "dry-run"   # FR-030: dry-run result
    assert decisions[0]["dryRun"] is True


def test_run_reconcile_emits_decision_for_ineligible(captured):
    # Production-excluded resource must still produce a decision record (OBS-001).
    h = FakeHandler("Running")
    run_reconcile([_sel("/vmprod", eligible=False, reason="production-excluded")],
                  now=_monday_10am(), run_id="r1",
                  profile_provider=_profiles, handlers={"vm": h},
                  config=ReconcileConfig(dry_run=False))
    decisions = _dims(captured.records, telemetry.DECISION_EVENT)
    assert len(decisions) == 1
    assert decisions[0]["result"] == "production-excluded"
    assert decisions[0]["action"] == "none"


def test_run_reconcile_failed_result_for_alert(captured):
    # OBS-004 keys on result == "failed" with runId + resourceId present.
    h = FailHandler("Stopped")  # start will raise
    run_reconcile([_sel("/vm1")], now=_monday_10am(), run_id="r1",
                  profile_provider=_profiles, handlers={"vm": h},
                  config=ReconcileConfig(dry_run=False))
    decisions = _dims(captured.records, telemetry.DECISION_EVENT)
    failed = [d for d in decisions if d["result"] == "failed"]
    assert len(failed) == 1
    assert failed[0]["resourceId"] == "/vm1"
    assert "runId" in failed[0]


def test_run_reconcile_cap_reached_emits_event(captured):
    # 3 start-needed resources, cap=2 => capReached event (OBS-005) + 1 deferred.
    h = FakeHandler("Stopped")
    sels = [_sel(f"/vm{i}") for i in range(3)]
    run_reconcile(sels, now=_monday_10am(), run_id="r1",
                  profile_provider=_profiles, handlers={"vm": h},
                  config=ReconcileConfig(dry_run=True, max_actions_per_run=2))
    caps = _dims(captured.records, telemetry.CAP_REACHED_EVENT)
    assert len(caps) == 1
    assert caps[0]["cap"] == 2
    assert caps[0]["deferred"] == 1
    # And every evaluated resource still has a decision record.
    decisions = _dims(captured.records, telemetry.DECISION_EVENT)
    assert len(decisions) == 3
