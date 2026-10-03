"""Unit tests for ordering and safety controls (T-203)."""

from __future__ import annotations

import os
import sys

_SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from engine.models import ActionType, PlannedAction, ResourceRecord  # noqa: E402
from engine.ordering import is_transitional, order_and_limit_actions  # noqa: E402


def _action(key, rid, action, order, rtype=None):
    r = ResourceRecord(
        resource_id=rid, resource_type=rtype or "Microsoft.Compute/virtualMachines",
        handler_key=key, subscription_id="s1", resource_group="rg1",
    )
    return PlannedAction(r, action, "Running", "r", "p", order)


def test_starts_ascending_stops_descending():
    actions = [
        _action("vm", "vm-start", ActionType.START, 3),
        _action("db", "db-start", ActionType.START, 1),
        _action("aks", "aks-start", ActionType.START, 2),
        _action("vm", "vm-stop", ActionType.STOP, 3),
        _action("db", "db-stop", ActionType.STOP, 1),
    ]
    result = order_and_limit_actions(actions, max_actions_per_run=100)
    ids = [a.resource.resource_id for a in result.actions]
    # starts first ascending order: db(1), aks(2), vm(3); then stops descending: vm(3), db(1)
    assert ids == ["db-start", "aks-start", "vm-start", "vm-stop", "db-stop"]


def test_deny_listed_type_skipped():
    fw = _action("fw", "fw1", ActionType.STOP, 3, rtype="Microsoft.Network/azureFirewalls")
    result = order_and_limit_actions([fw], max_actions_per_run=100)
    assert result.actions == ()
    assert len(result.skipped) == 1
    assert result.skipped[0].reason == "deny-listed-type"


def test_max_actions_cap_truncates_and_flags():
    actions = [_action("vm", f"vm{i}", ActionType.START, 3) for i in range(5)]
    result = order_and_limit_actions(actions, max_actions_per_run=3)
    assert len(result.actions) == 3
    assert result.cap_reached is True
    assert len(result.skipped) == 2
    assert all(s.reason == "max-actions-cap" for s in result.skipped)


def test_cap_not_reached():
    actions = [_action("vm", f"vm{i}", ActionType.START, 3) for i in range(2)]
    result = order_and_limit_actions(actions, max_actions_per_run=3)
    assert result.cap_reached is False
    assert len(result.actions) == 2


def test_none_actions_ignored():
    a = _action("vm", "vm1", ActionType.NONE, 3)
    result = order_and_limit_actions([a], max_actions_per_run=100)
    assert result.actions == ()


def test_is_transitional_tokens():
    assert is_transitional("Starting")
    assert is_transitional("stopping")
    assert is_transitional("Updating")
    assert not is_transitional("Running")
    assert not is_transitional("Deallocated")  # terminal stopped state, not transitional
