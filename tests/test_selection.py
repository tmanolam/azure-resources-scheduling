"""Unit tests for engine selection (T-202)."""

from __future__ import annotations

import os
import sys

_SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from engine.models import ResourceRecord  # noqa: E402
from engine.selection import resolve_effective_tags, select_resources  # noqa: E402


def _vm(rid="/subscriptions/s1/resourceGroups/rg1/providers/Microsoft.Compute/virtualMachines/vm1",
        sub="s1", tags=None, rg_tags=None, sub_tags=None, handler="vm", rtype="Microsoft.Compute/virtualMachines"):
    return ResourceRecord(
        resource_id=rid, resource_type=rtype, handler_key=handler,
        subscription_id=sub, resource_group="rg1",
        tags=tags or {}, resource_group_tags=rg_tags or {}, subscription_tags=sub_tags or {},
    )


def _one(results):
    assert len(results) == 1
    return results[0]


def test_tag_precedence_resource_over_rg_over_sub():
    r = _vm(
        sub_tags={"schedule-profile": "sub-prof"},
        rg_tags={"schedule-profile": "rg-prof"},
        tags={"schedule-profile": "res-prof"},
    )
    assert resolve_effective_tags(r)["schedule-profile"] == "res-prof"


def test_tag_precedence_rg_over_sub_when_no_resource_tag():
    r = _vm(sub_tags={"schedule-profile": "sub-prof"}, rg_tags={"schedule-profile": "rg-prof"})
    assert resolve_effective_tags(r)["schedule-profile"] == "rg-prof"


def test_eligible_resource():
    r = _vm(tags={"schedule-profile": "weekday-0830-1730"})
    s = _one(select_resources([r], enabled_handler_keys=["vm"]))
    assert s.eligible is True
    assert s.profile_name == "weekday-0830-1730"
    assert s.order == 3  # default


def test_production_hard_exclusion_overrides_everything():
    # US-07: subscription env=prod + a valid profile tag => still excluded.
    r = _vm(sub_tags={"environment": "prod"}, tags={"schedule-profile": "weekday-0830-1730"})
    s = _one(select_resources([r], enabled_handler_keys=["vm"]))
    assert s.eligible is False
    assert s.reason == "production-excluded"


def test_production_tag_on_resource_does_not_opt_out_but_sub_tag_does():
    # Only the *subscription* environment tag triggers prod exclusion (BR-003/A-08).
    r = _vm(tags={"schedule-profile": "p", "environment": "prod"})
    s = _one(select_resources([r], enabled_handler_keys=["vm"]))
    assert s.eligible is True  # resource-level env=prod is not the hard rule


def test_production_exclusion_tag_key_case_insensitive():
    # N5: Azure tag names are case-insensitive; 'Environment' must still exclude.
    r = _vm(sub_tags={"Environment": "prod"}, tags={"schedule-profile": "p"})
    s = _one(select_resources([r], enabled_handler_keys=["vm"]))
    assert s.eligible is False
    assert s.reason == "production-excluded"


def test_production_exclusion_tag_key_and_value_mixed_case():
    # N5: 'ENVIRONMENT=Prod' must also exclude (value already lowercased).
    r = _vm(sub_tags={"ENVIRONMENT": "Prod"}, tags={"schedule-profile": "p"})
    s = _one(select_resources([r], enabled_handler_keys=["vm"]))
    assert s.eligible is False
    assert s.reason == "production-excluded"


def test_excluded_scope_subscription():
    r = _vm(tags={"schedule-profile": "p"}, sub="s1")
    s = _one(select_resources([r], enabled_handler_keys=["vm"],
                              exclude_scopes=["/subscriptions/s1"]))
    assert s.eligible is False
    assert s.reason == "excluded-scope"


def test_excluded_scope_resource_group_prefix():
    rid = "/subscriptions/s1/resourceGroups/rg1/providers/Microsoft.Compute/virtualMachines/vm1"
    r = _vm(rid=rid, tags={"schedule-profile": "p"})
    s = _one(select_resources([r], enabled_handler_keys=["vm"],
                              exclude_scopes=["/subscriptions/s1/resourceGroups/rg1"]))
    assert s.eligible is False
    assert s.reason == "excluded-scope"


def test_type_not_enabled():
    r = _vm(tags={"schedule-profile": "p"}, handler="aks")
    s = _one(select_resources([r], enabled_handler_keys=["vm"]))
    assert s.eligible is False
    assert s.reason == "type-not-enabled"


def test_schedule_disabled_opt_out():
    r = _vm(tags={"schedule-profile": "p", "schedule-enabled": "false"})
    s = _one(select_resources([r], enabled_handler_keys=["vm"]))
    assert s.eligible is False
    assert s.reason == "schedule-disabled"


def test_no_profile_tag_ignored():
    r = _vm(tags={})
    s = _one(select_resources([r], enabled_handler_keys=["vm"]))
    assert s.eligible is False
    assert s.reason == "no-profile"


def test_order_from_tag_and_default():
    r1 = _vm(tags={"schedule-profile": "p", "schedule-order": "1"})
    r2 = _vm(tags={"schedule-profile": "p"}, handler="aks", rtype="Microsoft.ContainerService/managedClusters")
    results = select_resources([r1, r2], enabled_handler_keys=["vm", "aks"],
                               default_order_by_handler={"aks": 2})
    assert results[0].order == 1       # from tag
    assert results[1].order == 2       # from default map


def test_invalid_order_falls_back_to_default():
    r = _vm(tags={"schedule-profile": "p", "schedule-order": "99"})  # out of 1-9
    s = _one(select_resources([r], enabled_handler_keys=["vm"]))
    assert s.order == 3


# --- M2: nested management-group exclusion via mg_chain ----------------------

def _vm_in_chain(chain, **kw):
    r = _vm(**kw)
    from dataclasses import replace
    return replace(r, mg_chain=tuple(c.lower() for c in chain))


def test_excluded_child_mg_inside_included_mg():
    # M2: resource's subscription sits under 'org-sandbox-team' which is a child
    # of the included 'org-sandbox'; excluding the child MG must exclude it.
    r = _vm_in_chain(["org", "org-sandbox", "org-sandbox-team"],
                     tags={"schedule-profile": "p"})
    s = _one(select_resources([r], enabled_handler_keys=["vm"],
                              exclude_scopes=["/providers/Microsoft.Management/managementGroups/org-sandbox-team"]))
    assert s.eligible is False
    assert s.reason == "excluded-scope"


def test_mg_exclude_not_in_chain_is_ignored():
    r = _vm_in_chain(["org", "org-sandbox"], tags={"schedule-profile": "p"})
    s = _one(select_resources([r], enabled_handler_keys=["vm"],
                              exclude_scopes=["/providers/Microsoft.Management/managementGroups/org-platform"]))
    assert s.eligible is True
