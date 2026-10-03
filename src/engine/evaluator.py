"""Pure desired-state evaluator for the Azure Resource Power Scheduler.

This module contains the highest-risk logic of the system and is deliberately
**pure**: it performs no Azure calls, no I/O and no clock reads. Everything it
needs is passed in. This satisfies NFR-009 (desired-state evaluation shall be a
pure function covered by unit tests) and makes timezone / midnight-crossing /
override behaviour unit-testable offline.

Requirements implemented here:

- FR-002  Evaluate time in each profile's own IANA timezone (independent of UTC).
- FR-003  Determine desired state (Running/Stopped) from profile run windows.
- FR-006  Apply per-order start offsets (startOffsetMinutesByOrder).
- FR-020  A valid future override holds schedule-override-state (default running).
- BR-004  A valid future override always takes precedence over the schedule.
- BR-005  A tag referencing an unknown profile => no action, logged as a warning.
- FR-026  Invalid override date/state => warning, override ignored.

The engine (Phase 2) is responsible for reading actual state and acting only on
differences (FR-004); this module only computes the *desired* state.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping, Optional, Sequence
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

__all__ = [
    "DesiredState",
    "Decision",
    "RunWindow",
    "Profile",
    "evaluate_desired_state",
    "parse_profile",
]

# Day-of-week tokens as used in profile JSON, Monday=0 to match datetime.weekday().
_WEEKDAY_TOKENS: dict[str, int] = {
    "Mon": 0,
    "Tue": 1,
    "Wed": 2,
    "Thu": 3,
    "Fri": 4,
    "Sat": 5,
    "Sun": 6,
}


class DesiredState(str, Enum):
    """The computed desired power state of a resource."""

    RUNNING = "Running"
    STOPPED = "Stopped"
    NO_ACTION = "NoAction"  # e.g. unknown profile (BR-005): engine must not act


@dataclass(frozen=True)
class Decision:
    """Result of a desired-state evaluation.

    Attributes:
        state:   The desired state (RUNNING/STOPPED/NO_ACTION).
        reason:  Machine-friendly reason code for logging (OBS-001).
        warning: Optional human-readable warning (BR-005, FR-026).
    """

    state: DesiredState
    reason: str
    warning: Optional[str] = None


@dataclass(frozen=True)
class RunWindow:
    """A single run window within a profile.

    ``days`` are datetime.weekday() integers (Mon=0). ``start``/``stop`` are
    minutes-since-midnight in the profile timezone. When ``stop <= start`` the
    window crosses midnight (e.g. 20:00->02:00).
    """

    days: frozenset[int]
    start_minute: int
    stop_minute: int

    @property
    def crosses_midnight(self) -> bool:
        return self.stop_minute <= self.start_minute


@dataclass(frozen=True)
class Profile:
    """A parsed, validated schedule profile (§6.2)."""

    name: str
    timezone: str
    run_windows: Sequence[RunWindow]
    start_offset_by_order: Mapping[int, int] = field(default_factory=dict)

    def tzinfo(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


class ProfileError(ValueError):
    """Raised when a profile JSON is structurally invalid."""


def _parse_hhmm(value: str) -> int:
    """Parse 'HH:MM' into minutes since midnight. Raises ProfileError if bad."""
    try:
        hh, mm = value.split(":")
        h, m = int(hh), int(mm)
    except (ValueError, AttributeError) as exc:
        raise ProfileError(f"invalid time literal: {value!r}") from exc
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise ProfileError(f"time out of range: {value!r}")
    return h * 60 + m


def parse_profile(name: str, raw: Mapping[str, object]) -> Profile:
    """Validate and parse a raw profile mapping (parsed JSON) into a Profile.

    Raises ProfileError on structural problems (invalid timezone, bad time,
    unknown weekday token, empty run windows).
    """
    tz = raw.get("timezone")
    if not isinstance(tz, str) or not tz:
        raise ProfileError(f"profile {name!r}: missing or invalid 'timezone'")
    try:
        ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ProfileError(f"profile {name!r}: unknown IANA timezone {tz!r}") from exc

    raw_windows = raw.get("runWindows")
    if not isinstance(raw_windows, list) or not raw_windows:
        raise ProfileError(f"profile {name!r}: 'runWindows' must be a non-empty list")

    windows: list[RunWindow] = []
    for i, w in enumerate(raw_windows):
        if not isinstance(w, Mapping):
            raise ProfileError(f"profile {name!r}: runWindows[{i}] must be an object")
        days_raw = w.get("days")
        if not isinstance(days_raw, list) or not days_raw:
            raise ProfileError(f"profile {name!r}: runWindows[{i}].days must be a non-empty list")
        days: set[int] = set()
        for d in days_raw:
            if d not in _WEEKDAY_TOKENS:
                raise ProfileError(f"profile {name!r}: unknown day token {d!r}")
            days.add(_WEEKDAY_TOKENS[d])
        start = _parse_hhmm(str(w.get("start")))
        stop = _parse_hhmm(str(w.get("stop")))
        windows.append(RunWindow(frozenset(days), start, stop))

    offsets: dict[int, int] = {}
    raw_offsets = raw.get("startOffsetMinutesByOrder") or {}
    if not isinstance(raw_offsets, Mapping):
        raise ProfileError(f"profile {name!r}: 'startOffsetMinutesByOrder' must be an object")
    for k, v in raw_offsets.items():
        try:
            offsets[int(k)] = int(v)
        except (TypeError, ValueError) as exc:
            raise ProfileError(
                f"profile {name!r}: invalid startOffsetMinutesByOrder entry {k!r}={v!r}"
            ) from exc

    return Profile(
        name=name,
        timezone=tz,
        run_windows=tuple(windows),
        start_offset_by_order=offsets,
    )


def _minute_in_window(window: RunWindow, weekday: int, minute_of_day: int) -> bool:
    """Return True if (weekday, minute_of_day) falls inside the run window.

    Handles midnight-crossing windows: a window Mon 20:00->02:00 covers Monday
    20:00-23:59 *and* Tuesday 00:00-01:59. The ``days`` set lists the days on
    which the window *starts*.
    """
    if not window.crosses_midnight:
        return weekday in window.days and window.start_minute <= minute_of_day < window.stop_minute

    # Crosses midnight: the window is active either
    #   (a) on a start day at/after start_minute, or
    #   (b) on the day *after* a start day, before stop_minute.
    if weekday in window.days and minute_of_day >= window.start_minute:
        return True
    prev_day = (weekday - 1) % 7
    if prev_day in window.days and minute_of_day < window.stop_minute:
        return True
    return False


def _apply_start_offset(window: RunWindow, offset_minutes: int) -> RunWindow:
    """Return a copy of the window with the start shifted by offset_minutes.

    A negative offset makes the resource start earlier (FR-006). The start is
    clamped to [0, 1439] within the same day; the stop is unchanged.
    """
    if offset_minutes == 0:
        return window
    new_start = max(0, min(1439, window.start_minute + offset_minutes))
    return RunWindow(window.days, new_start, window.stop_minute)


def evaluate_desired_state(
    profile: Optional[Profile],
    now: _dt.datetime,
    *,
    order: int = 3,
    override_state: Optional[str] = None,
    override_until: Optional[str] = None,
) -> Decision:
    """Compute the desired power state for a resource at ``now``.

    Args:
        profile: Parsed profile, or ``None`` if the resource's schedule-profile
            tag references a profile that does not exist (BR-005).
        now: The evaluation instant. Must be timezone-aware (UTC recommended);
            it is converted into the profile timezone (FR-002).
        order: The resource's schedule-order (default 3), used to look up the
            per-order start offset (FR-006).
        override_state: Raw ``schedule-override-state`` tag value, if any.
        override_until: Raw ``schedule-override-until`` tag value (ISO 8601 with
            offset), if any.

    Returns:
        A Decision with the desired state and a reason code. The engine acts only
        when desired != actual (FR-004); NO_ACTION means never act.
    """
    if now.tzinfo is None:
        raise ValueError("`now` must be timezone-aware")

    # --- Overrides take precedence over the schedule (BR-004, FR-020) ---------
    # Evaluated first. A valid, active override wins outright. An invalid
    # override (FR-026) produces a warning but falls through to the schedule.
    override_result = _evaluate_override(now, override_state, override_until)
    if override_result.decision is not None:
        return override_result.decision

    # --- Unknown / missing profile => no action (BR-005) ----------------------
    if profile is None:
        return Decision(
            DesiredState.NO_ACTION,
            reason="unknown-profile",
            warning="schedule-profile tag references an undefined profile",
        )

    # --- Schedule evaluation in the profile timezone (FR-002, FR-003) ---------
    local = now.astimezone(profile.tzinfo())
    weekday = local.weekday()
    minute_of_day = local.hour * 60 + local.minute
    offset = profile.start_offset_by_order.get(order, 0)

    for window in profile.run_windows:
        effective = _apply_start_offset(window, offset)
        if _minute_in_window(effective, weekday, minute_of_day):
            return Decision(
                DesiredState.RUNNING,
                reason="in-run-window",
                warning=override_result.warning,
            )

    return Decision(
        DesiredState.STOPPED,
        reason="outside-run-window",
        warning=override_result.warning,
    )


@dataclass(frozen=True)
class _OverrideResult:
    """Internal: outcome of override evaluation.

    - ``decision`` set => a valid active override wins; return it directly.
    - ``decision`` None => no active override; fall through to the schedule.
      ``warning`` may still be set to surface an invalid-override warning
      (FR-026) alongside the schedule decision.
    """

    decision: Optional[Decision] = None
    warning: Optional[str] = None


def _evaluate_override(
    now: _dt.datetime,
    override_state: Optional[str],
    override_until: Optional[str],
) -> "_OverrideResult":
    """Resolve override tags.

    Returns an _OverrideResult. A valid, active override sets ``decision``.
    An expired override or no tags returns an empty result (fall through to
    schedule). An invalid date or state (FR-026) returns an empty decision with
    a ``warning`` so the caller warns and still evaluates the schedule.
    """
    if override_until is None and override_state is None:
        return _OverrideResult()

    # schedule-override-until is required to activate an override. A lone state
    # tag with no 'until' is meaningless and ignored (§6.1).
    if override_until is None:
        return _OverrideResult()

    parsed = _parse_iso8601(override_until)
    if parsed is None:
        # FR-026: invalid date => warn and ignore (fall through to schedule).
        return _OverrideResult(
            warning=f"invalid schedule-override-until {override_until!r}; override ignored"
        )

    if parsed <= now:
        # Expired override: ignore, resume schedule (FR-020). Not an error.
        return _OverrideResult()

    # Active override. Default state is running (FR-020 / §6.1).
    state_raw = (override_state or "running").strip().lower()
    if state_raw == "running":
        return _OverrideResult(Decision(DesiredState.RUNNING, reason="override-active-running"))
    if state_raw == "stopped":
        return _OverrideResult(Decision(DesiredState.STOPPED, reason="override-active-stopped"))

    # FR-026: invalid state value => warn and ignore the override.
    return _OverrideResult(
        warning=f"invalid schedule-override-state {override_state!r}; override ignored"
    )


def _parse_iso8601(value: str) -> Optional[_dt.datetime]:
    """Parse an ISO 8601 datetime with offset into an aware datetime.

    Returns None if the value cannot be parsed or has no timezone offset
    (an override-until without an offset is ambiguous and treated as invalid).
    """
    if not isinstance(value, str):
        return None
    text = value.strip()
    # Accept a trailing 'Z' as UTC.
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = _dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed
