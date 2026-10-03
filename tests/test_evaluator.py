"""Unit tests for the pure desired-state evaluator (T-102).

Satisfies NFR-009 and mitigates R-06 (wrong timezone). Covers:
- per-profile IANA timezone, independent of UTC input (FR-002)
- in/out of run window, weekday boundaries (FR-003)
- midnight-crossing windows
- per-order start offsets (FR-006, US-03)
- active / expired / invalid overrides (FR-020, FR-026, BR-004, US-02, US-06)
- unknown profile => no action (BR-005)

Input instants are supplied in UTC to prove the evaluator converts into the
profile timezone itself. Asia/Bangkok is UTC+7 with no DST.
"""

from __future__ import annotations

import datetime as _dt
import os
import sys
from zoneinfo import ZoneInfo

import pytest

# Make src/ importable without packaging/installation.
_SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from engine.evaluator import (  # noqa: E402
    DesiredState,
    Profile,
    ProfileError,
    evaluate_desired_state,
    parse_profile,
)

BKK = ZoneInfo("Asia/Bangkok")
UTC = _dt.timezone.utc

STANDARD_RAW = {
    "timezone": "Asia/Bangkok",
    "runWindows": [
        {"days": ["Mon", "Tue", "Wed", "Thu", "Fri"], "start": "08:30", "stop": "17:30"}
    ],
    "startOffsetMinutesByOrder": {"1": -30, "2": -15, "3": 0},
}


@pytest.fixture
def standard() -> Profile:
    return parse_profile("weekday-0830-1730", STANDARD_RAW)


def _utc_from_bkk(y, mo, d, h, mi) -> _dt.datetime:
    """Build a UTC instant corresponding to the given Bangkok wall-clock time."""
    return _dt.datetime(y, mo, d, h, mi, tzinfo=BKK).astimezone(UTC)


# --- parse_profile validation ------------------------------------------------

def test_parse_valid_profile(standard: Profile):
    assert standard.timezone == "Asia/Bangkok"
    assert standard.start_offset_by_order == {1: -30, 2: -15, 3: 0}
    assert len(standard.run_windows) == 1


@pytest.mark.parametrize(
    "raw",
    [
        {"timezone": "", "runWindows": [{"days": ["Mon"], "start": "08:00", "stop": "17:00"}]},
        {"timezone": "Not/AZone", "runWindows": [{"days": ["Mon"], "start": "08:00", "stop": "17:00"}]},
        {"timezone": "Asia/Bangkok", "runWindows": []},
        {"timezone": "Asia/Bangkok", "runWindows": [{"days": ["Funday"], "start": "08:00", "stop": "17:00"}]},
        {"timezone": "Asia/Bangkok", "runWindows": [{"days": ["Mon"], "start": "25:00", "stop": "17:00"}]},
    ],
)
def test_parse_invalid_profile_raises(raw):
    with pytest.raises(ProfileError):
        parse_profile("bad", raw)


# --- FR-002: timezone independence -------------------------------------------

def test_timezone_is_profile_local_not_utc(standard: Profile):
    # 02:00 UTC on a Monday == 09:00 Bangkok Monday => inside window => RUNNING.
    now = _dt.datetime(2026, 10, 5, 2, 0, tzinfo=UTC)  # Mon
    d = evaluate_desired_state(standard, now, order=3)
    assert d.state is DesiredState.RUNNING
    # Same instant without conversion would be 02:00 "UTC Monday" => outside;
    # proves the evaluator converts to Bangkok.


def test_naive_now_rejected(standard: Profile):
    with pytest.raises(ValueError):
        evaluate_desired_state(standard, _dt.datetime(2026, 10, 5, 2, 0), order=3)


# --- FR-003: run window boundaries -------------------------------------------

def test_running_during_window(standard: Profile):
    d = evaluate_desired_state(standard, _utc_from_bkk(2026, 10, 5, 10, 0), order=3)  # Mon 10:00
    assert d.state is DesiredState.RUNNING
    assert d.reason == "in-run-window"


def test_stopped_before_start(standard: Profile):
    d = evaluate_desired_state(standard, _utc_from_bkk(2026, 10, 5, 8, 0), order=3)  # Mon 08:00
    assert d.state is DesiredState.STOPPED


def test_start_boundary_inclusive(standard: Profile):
    d = evaluate_desired_state(standard, _utc_from_bkk(2026, 10, 5, 8, 30), order=3)  # Mon 08:30
    assert d.state is DesiredState.RUNNING


def test_stop_boundary_exclusive(standard: Profile):
    # 17:30 is the stop minute => already stopped (exclusive upper bound).
    d = evaluate_desired_state(standard, _utc_from_bkk(2026, 10, 5, 17, 30), order=3)
    assert d.state is DesiredState.STOPPED


def test_weekend_stopped(standard: Profile):
    d_sat = evaluate_desired_state(standard, _utc_from_bkk(2026, 10, 10, 10, 0), order=3)  # Sat
    d_sun = evaluate_desired_state(standard, _utc_from_bkk(2026, 10, 11, 10, 0), order=3)  # Sun
    assert d_sat.state is DesiredState.STOPPED
    assert d_sun.state is DesiredState.STOPPED


# --- FR-006: per-order start offsets (US-03) ---------------------------------

def test_order1_starts_30min_early(standard: Profile):
    # order 1 offset -30 => starts 08:00. At 08:00 Mon, order1 RUNNING, order3 STOPPED.
    at_0800 = _utc_from_bkk(2026, 10, 5, 8, 0)
    assert evaluate_desired_state(standard, at_0800, order=1).state is DesiredState.RUNNING
    assert evaluate_desired_state(standard, at_0800, order=3).state is DesiredState.STOPPED


def test_order2_starts_15min_early(standard: Profile):
    # order 2 offset -15 => starts 08:15. At 08:15 order2 RUNNING; order3 still STOPPED.
    at_0815 = _utc_from_bkk(2026, 10, 5, 8, 15)
    assert evaluate_desired_state(standard, at_0815, order=2).state is DesiredState.RUNNING
    assert evaluate_desired_state(standard, at_0815, order=3).state is DesiredState.STOPPED


def test_unknown_order_uses_zero_offset(standard: Profile):
    # order 9 has no offset => default 0 => behaves like start 08:30.
    assert evaluate_desired_state(standard, _utc_from_bkk(2026, 10, 5, 8, 0), order=9).state is DesiredState.STOPPED
    assert evaluate_desired_state(standard, _utc_from_bkk(2026, 10, 5, 8, 30), order=9).state is DesiredState.RUNNING


# --- Midnight-crossing windows -----------------------------------------------

@pytest.fixture
def night() -> Profile:
    return parse_profile(
        "night-2000-0200",
        {
            "timezone": "Asia/Bangkok",
            "runWindows": [{"days": ["Mon"], "start": "20:00", "stop": "02:00"}],
        },
    )


def test_midnight_crossing_same_day(night: Profile):
    # Mon 21:00 Bangkok => inside.
    assert evaluate_desired_state(night, _utc_from_bkk(2026, 10, 5, 21, 0)).state is DesiredState.RUNNING


def test_midnight_crossing_next_day_before_stop(night: Profile):
    # Tue 01:00 Bangkok => still inside the Monday-started window.
    assert evaluate_desired_state(night, _utc_from_bkk(2026, 10, 6, 1, 0)).state is DesiredState.RUNNING


def test_midnight_crossing_next_day_after_stop(night: Profile):
    # Tue 02:00 Bangkok => stop is exclusive => stopped.
    assert evaluate_desired_state(night, _utc_from_bkk(2026, 10, 6, 2, 0)).state is DesiredState.STOPPED


def test_midnight_crossing_before_start(night: Profile):
    # Mon 19:59 Bangkok => before start.
    assert evaluate_desired_state(night, _utc_from_bkk(2026, 10, 5, 19, 59)).state is DesiredState.STOPPED


# --- Overrides: FR-020, FR-026, BR-004 (US-02, US-06) ------------------------

def test_active_override_running_beats_schedule(standard: Profile):
    # Friday 18:00 Bangkok (normally stopped) but override running until 21:00.
    now = _utc_from_bkk(2026, 10, 9, 18, 0)  # Fri
    d = evaluate_desired_state(
        standard, now, order=3,
        override_state="running", override_until="2026-10-09T21:00+07:00",
    )
    assert d.state is DesiredState.RUNNING
    assert d.reason == "override-active-running"


def test_expired_override_resumes_schedule(standard: Profile):
    # First cycle after 21:00 => override expired => schedule says stopped (Fri 21:30).
    now = _utc_from_bkk(2026, 10, 9, 21, 30)
    d = evaluate_desired_state(
        standard, now, order=3,
        override_state="running", override_until="2026-10-09T21:00+07:00",
    )
    assert d.state is DesiredState.STOPPED
    assert d.reason == "outside-run-window"


def test_override_stopped_during_business_hours(standard: Profile):
    # US-06: stop a resource group for the afternoon. Mon 14:00, override stopped until 17:30.
    now = _utc_from_bkk(2026, 10, 5, 14, 0)
    d = evaluate_desired_state(
        standard, now, order=3,
        override_state="stopped", override_until="2026-10-05T17:30+07:00",
    )
    assert d.state is DesiredState.STOPPED
    assert d.reason == "override-active-stopped"


def test_override_default_state_is_running(standard: Profile):
    # override-until set, state omitted => default running (§6.1).
    now = _utc_from_bkk(2026, 10, 10, 10, 0)  # Sat, normally stopped
    d = evaluate_desired_state(standard, now, order=3, override_until="2026-10-10T23:00+07:00")
    assert d.state is DesiredState.RUNNING


def test_invalid_override_date_falls_through_with_warning(standard: Profile):
    # FR-026: unparseable date => warn, ignore override, use schedule. Mon 10:00 => running.
    now = _utc_from_bkk(2026, 10, 5, 10, 0)
    d = evaluate_desired_state(
        standard, now, order=3,
        override_state="stopped", override_until="not-a-date",
    )
    assert d.state is DesiredState.RUNNING  # schedule wins
    assert d.warning is not None and "invalid schedule-override-until" in d.warning


def test_invalid_override_state_falls_through_with_warning(standard: Profile):
    # FR-026: invalid state => warn, ignore override, use schedule. Sat => stopped.
    now = _utc_from_bkk(2026, 10, 10, 10, 0)
    d = evaluate_desired_state(
        standard, now, order=3,
        override_state="halted", override_until="2026-10-10T23:00+07:00",
    )
    assert d.state is DesiredState.STOPPED  # schedule wins (weekend)
    assert d.warning is not None and "invalid schedule-override-state" in d.warning


def test_override_until_without_offset_is_invalid(standard: Profile):
    # No UTC offset => ambiguous => treated as invalid => ignored with warning.
    now = _utc_from_bkk(2026, 10, 10, 10, 0)
    d = evaluate_desired_state(
        standard, now, order=3,
        override_state="running", override_until="2026-10-10T23:00",
    )
    assert d.state is DesiredState.STOPPED
    assert d.warning is not None


def test_override_until_accepts_z_suffix(standard: Profile):
    # 'Z' == UTC. Sat 10:00 BKK == 03:00Z; override until 10:00Z (future) => running.
    now = _utc_from_bkk(2026, 10, 10, 10, 0)
    d = evaluate_desired_state(
        standard, now, order=3,
        override_state="running", override_until="2026-10-10T10:00Z",
    )
    assert d.state is DesiredState.RUNNING


# --- BR-005: unknown profile -------------------------------------------------

def test_unknown_profile_no_action():
    now = _dt.datetime(2026, 10, 5, 2, 0, tzinfo=UTC)
    d = evaluate_desired_state(None, now, order=3)
    assert d.state is DesiredState.NO_ACTION
    assert d.reason == "unknown-profile"
    assert d.warning is not None


def test_unknown_profile_but_active_override_still_applies():
    # Override precedence (BR-004) applies even when the profile is unknown.
    now = _dt.datetime(2026, 10, 5, 2, 0, tzinfo=UTC)
    d = evaluate_desired_state(
        None, now, order=3,
        override_state="stopped", override_until="2026-12-31T00:00+07:00",
    )
    assert d.state is DesiredState.STOPPED
    assert d.reason == "override-active-stopped"
