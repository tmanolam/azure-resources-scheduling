"""Unit tests for the App Configuration loader (engine.config) and the runtime
assembly (runtime.build_runtime) — all with fakes, no Azure SDK required."""

from __future__ import annotations

import json
import os
import sys
import types

import pytest

_SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from engine.config import (  # noqa: E402
    LoadedConfig,
    Settings,
    load_from_app_configuration,
    parse_config,
)
from engine.discovery import QueryPage  # noqa: E402
from engine.evaluator import Profile  # noqa: E402
import runtime  # noqa: E402

STD_PROFILE = {
    "timezone": "Asia/Bangkok",
    "runWindows": [{"days": ["Mon", "Tue", "Wed", "Thu", "Fri"], "start": "08:30", "stop": "17:30"}],
    "startOffsetMinutesByOrder": {"1": -30, "2": -15, "3": 0},
}


def _kv():
    return {
        "pwrsched:resourceTypes": json.dumps(["vm", "aks"]),
        "pwrsched:scopes:include": json.dumps(["/providers/Microsoft.Management/managementGroups/lz"]),
        "pwrsched:scopes:exclude": json.dumps(["/providers/Microsoft.Management/managementGroups/platform"]),
        "pwrsched:dryRun": "true",
        "pwrsched:maxActionsPerRun": "200",
        "pwrsched:reconcileSchedule": "0 */15 * * * *",
        "pwrsched:profiles:weekday-0830-1730": json.dumps(STD_PROFILE),
    }


# --- parse_config ------------------------------------------------------------

def test_parse_config_settings():
    cfg = parse_config(_kv())
    s = cfg.settings
    assert s.enabled_resource_types == ["vm", "aks"]
    assert s.include_scopes == ["/providers/Microsoft.Management/managementGroups/lz"]
    assert s.exclude_scopes == ["/providers/Microsoft.Management/managementGroups/platform"]
    assert s.dry_run is True
    assert s.max_actions_per_run == 200
    assert s.reconcile_schedule == "0 */15 * * * *"


def test_parse_config_profiles_and_provider():
    cfg = parse_config(_kv())
    assert "weekday-0830-1730" in cfg.profiles
    assert isinstance(cfg.profiles["weekday-0830-1730"], Profile)
    assert cfg.profile_provider("weekday-0830-1730") is not None
    assert cfg.profile_provider("nope") is None  # BR-005


def test_parse_config_dry_run_false():
    kv = _kv()
    kv["pwrsched:dryRun"] = "false"
    assert parse_config(kv).settings.dry_run is False


def test_parse_config_invalid_profile_skipped():
    kv = _kv()
    kv["pwrsched:profiles:broken"] = json.dumps({"timezone": "Not/AZone", "runWindows": []})
    cfg = parse_config(kv)
    assert "broken" not in cfg.profiles       # invalid profile skipped
    assert "weekday-0830-1730" in cfg.profiles  # valid one still loaded


def test_parse_config_defaults_when_missing():
    cfg = parse_config({})
    assert cfg.settings.enabled_resource_types == []
    assert cfg.settings.dry_run is True        # safe default
    assert cfg.settings.max_actions_per_run == 200
    assert cfg.profiles == {}


def test_parse_config_bad_int_falls_back():
    kv = _kv()
    kv["pwrsched:maxActionsPerRun"] = "not-a-number"
    assert parse_config(kv).settings.max_actions_per_run == 200


# --- load_from_app_configuration (injected list_fn) --------------------------

def test_load_from_app_configuration_with_fake_client():
    settings_objs = [
        types.SimpleNamespace(key=k, value=v) for k, v in _kv().items()
    ]
    cfg = load_from_app_configuration("https://appcs.example", list_fn=lambda: settings_objs)
    assert cfg.settings.enabled_resource_types == ["vm", "aks"]
    assert cfg.profile_provider("weekday-0830-1730") is not None


# --- runtime.build_runtime (fully injected) ----------------------------------

def test_build_runtime_assembles_handlers_and_discover():
    cfg = parse_config(_kv())

    rows = [{
        "id": "/subscriptions/s1/resourceGroups/rg1/providers/Microsoft.Compute/virtualMachines/vm1",
        "type": "Microsoft.Compute/virtualMachines",
        "subscriptionId": "s1", "resourceGroup": "rg1", "location": "sea",
        "tags": {"schedule-profile": "weekday-0830-1730"},
    }]

    def fake_query_fn(query, scopes, skip_token):
        return QueryPage(data=rows, skip_token=None)

    # Fake client factories for the enabled handler keys (vm, aks).
    factories = {k: (lambda sub: object()) for k in cfg.settings.enabled_resource_types}

    rt = runtime.build_runtime(
        "https://appcs.example",
        config=cfg,
        query_fn=fake_query_fn,
        client_factories=factories,
    )

    assert set(rt.handlers) == {"vm", "aks"}
    assert rt.dry_run is True
    assert rt.max_actions_per_run == 200
    assert rt.profile_provider("weekday-0830-1730") is not None

    discovered = rt.discover()
    assert len(discovered) == 1
    assert discovered[0].handler_key == "vm"


def test_default_client_factories_builds_for_known_keys():
    # Does not instantiate clients (lazy); just builds the factory callables.
    factories = runtime.default_client_factories(credential=object(), enabled_handler_keys=["vm", "aks", "appgw"])
    assert set(factories) == {"vm", "aks", "appgw"}
    assert all(callable(f) for f in factories.values())


def test_default_client_factories_skips_unknown_key():
    factories = runtime.default_client_factories(credential=object(), enabled_handler_keys=["vm", "bogus"])
    assert set(factories) == {"vm"}
