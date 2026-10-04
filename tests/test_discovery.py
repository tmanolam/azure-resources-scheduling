"""Unit tests for engine discovery (T-201)."""

from __future__ import annotations

import os
import sys

_SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from engine.discovery import (  # noqa: E402
    QueryPage,
    build_kql_query,
    discover_resources,
)
from engine.selection import select_resources  # noqa: E402


def _row(rid, rtype, sub="s1", rg="rg1", tags=None, rg_tags=None, sub_tags=None,
         with_sub_container=True):
    """Build a raw Resource Graph row shaped like the joined query output.

    ``with_sub_container=False`` simulates the subscription container row not
    joining (identity lacks Microsoft.Resources/subscriptions/read). With a
    ``leftouter`` join Resource Graph still returns every projected column, but
    the join key ``subId`` (and the other subscription columns) is ``null`` —
    this is the real shape the C1 fail-safe must detect (finding N1), so the
    keys are present with ``None`` values rather than absent.
    """
    row = {
        "id": rid, "type": rtype, "subscriptionId": sub, "resourceGroup": rg,
        "location": "southeastasia",
        "tags": tags if tags is not None else {"schedule-profile": "weekday-0830-1730"},
        "resourceGroupTags": rg_tags or {},
    }
    if with_sub_container:
        row["subId"] = sub
        row["subscriptionTags"] = sub_tags or {}
        row["mgChain"] = []
    else:
        # Unmatched leftouter join: columns present but null.
        row["subId"] = None
        row["subscriptionTags"] = None
        row["mgChain"] = None
    return row


def test_build_kql_includes_only_enabled_types():
    q = build_kql_query(["vm", "aks"])
    assert "microsoft.compute/virtualmachines" in q
    assert "microsoft.containerservice/managedclusters" in q
    assert "microsoft.dbformysql/flexibleservers" not in q
    assert "schedule-profile" in q  # opt-in pre-filter


def test_build_kql_joins_resourcecontainers_for_inherited_tags():
    # C1/C2: the query must join resourcecontainers and project the inherited
    # tag maps, and resolve opt-in across resource/RG/subscription via coalesce.
    q = build_kql_query(["vm"])
    assert "ResourceContainers" in q
    assert "microsoft.resources/subscriptions/resourcegroups" in q
    assert "microsoft.resources/subscriptions" in q
    assert "resourceGroupTags" in q
    assert "subscriptionTags" in q
    assert "coalesce(" in q
    assert "mgChain" in q


def test_build_kql_projects_sub_id_join_key():
    # N1: the subscription join key must be projected so the engine can detect
    # a null (unmatched) subscription row for the BR-003 fail-safe.
    q = build_kql_query(["vm"])
    assert "subId = subscriptionId" in q
    assert ", subId," in q or " subId," in q  # kept in the final projection


def test_build_kql_lowercases_both_sides_of_rg_join():
    # N4: both sides of the RG join must be lowercased so a mixed-case
    # resourceGroup on the Resources row still matches the RG container.
    q = build_kql_query(["vm"])
    assert "rgKey = tolower(resourceGroup)" in q
    assert "rgName = tolower(name)" in q
    assert "$left.rgKey == $right.rgName" in q


def test_build_kql_projects_power_state():
    # M1: planning reads actual state from Resource Graph, so the query must
    # project a coalesced powerState across the type-specific properties.
    q = build_kql_query(["vm", "aks", "postgres-flex", "appgw"])
    assert "powerState" in q
    assert "instanceView.powerState.code" in q   # vm
    assert "properties.powerState.code" in q      # aks
    assert "properties.state" in q                # db/sqlmi
    assert "properties.operationalState" in q     # appgw


def test_discovery_populates_power_state():
    row = _row(_VM_RID, _VM_TYPE)
    row["powerState"] = "PowerState/running"
    recs = discover_resources(lambda q, s, t: QueryPage([row], None),
                              include_scopes=["mg"], enabled_handler_keys=["vm"])
    assert recs[0].power_state == "running"  # prefix stripped


def test_discover_single_page():
    rows = [
        _row("/subscriptions/s1/rg/vm1", "Microsoft.Compute/virtualMachines"),
        _row("/subscriptions/s1/rg/aks1", "Microsoft.ContainerService/managedClusters"),
    ]
    calls = []

    def query_fn(query, scopes, skip_token):
        calls.append((scopes, skip_token))
        return QueryPage(data=rows, skip_token=None)

    recs = discover_resources(query_fn, include_scopes=["/providers/.../mg"],
                              enabled_handler_keys=["vm", "aks"])
    assert len(recs) == 2
    assert recs[0].handler_key == "vm"
    assert recs[1].handler_key == "aks"
    assert len(calls) == 1


def test_discover_follows_paging():
    page1 = QueryPage(data=[_row("/s/1/vm1", "Microsoft.Compute/virtualMachines")], skip_token="tok1")
    page2 = QueryPage(data=[_row("/s/1/vm2", "Microsoft.Compute/virtualMachines")], skip_token="tok2")
    page3 = QueryPage(data=[_row("/s/1/vm3", "Microsoft.Compute/virtualMachines")], skip_token=None)
    pages = [page1, page2, page3]
    seen_tokens = []

    def query_fn(query, scopes, skip_token):
        seen_tokens.append(skip_token)
        return pages.pop(0)

    recs = discover_resources(query_fn, include_scopes=["mg"], enabled_handler_keys=["vm"])
    assert len(recs) == 3
    assert seen_tokens == [None, "tok1", "tok2"]  # FR-014 paging


def test_discover_skips_unmappable_type():
    rows = [_row("/s/1/x", "Microsoft.Unknown/thing")]
    recs = discover_resources(lambda q, s, t: QueryPage(rows, None),
                              include_scopes=["mg"], enabled_handler_keys=["vm"])
    assert recs == []


# --- C1/C2 end-to-end: discovery populates inherited tags, selection uses them

_VM_RID = "/subscriptions/s1/resourceGroups/rg1/providers/Microsoft.Compute/virtualMachines/vm1"
_VM_TYPE = "Microsoft.Compute/virtualMachines"


def _discover_one(row):
    recs = discover_resources(lambda q, s, t: QueryPage([row], None),
                              include_scopes=["mg"], enabled_handler_keys=["vm"])
    assert len(recs) == 1
    return recs[0]


def test_discovery_populates_inherited_tag_maps():
    rec = _discover_one(_row(_VM_RID, _VM_TYPE,
                             sub_tags={"environment": "prod"},
                             rg_tags={"schedule-profile": "rg-prof"}))
    assert rec.subscription_tags == {"environment": "prod"}
    assert rec.resource_group_tags == {"schedule-profile": "rg-prof"}
    assert rec.subscription_container_seen is True


def test_c1_production_excluded_end_to_end_from_raw_row():
    # C1: a prod-subscription VM with its own profile tag must be excluded once
    # discovery actually populates subscription_tags from the join.
    rec = _discover_one(_row(_VM_RID, _VM_TYPE,
                             tags={"schedule-profile": "weekday-0830-1730"},
                             sub_tags={"environment": "prod"}))
    results = select_resources([rec], enabled_handler_keys=["vm"])
    assert len(results) == 1
    assert results[0].eligible is False
    assert results[0].reason == "production-excluded"


def test_c1_fail_safe_when_subscription_container_null():
    # N1: subscription row did not join -> leftouter leaves subId (and the other
    # subscription columns) null, which is the real Resource Graph shape. The
    # resource must be ineligible, not assumed safe.
    rec = _discover_one(_row(_VM_RID, _VM_TYPE,
                             tags={"schedule-profile": "weekday-0830-1730"},
                             with_sub_container=False))
    assert rec.subscription_container_seen is False
    results = select_resources([rec], enabled_handler_keys=["vm"])
    assert results[0].eligible is False
    assert results[0].reason == "subscription-tags-unavailable"


def test_c1_fail_safe_when_subscription_keys_absent():
    # Defensive: if a future query shape omits the subscription columns entirely
    # (keys absent), the fail-safe must still treat the resource as ineligible.
    row = _row(_VM_RID, _VM_TYPE, tags={"schedule-profile": "weekday-0830-1730"})
    for key in ("subId", "subscriptionTags", "mgChain"):
        row.pop(key, None)
    rec = _discover_one(row)
    assert rec.subscription_container_seen is False
    results = select_resources([rec], enabled_handler_keys=["vm"])
    assert results[0].eligible is False
    assert results[0].reason == "subscription-tags-unavailable"


def test_c2_profile_inherited_from_resource_group_end_to_end():
    # C2: resource has no own tags; RG supplies the profile -> eligible.
    rec = _discover_one(_row(_VM_RID, _VM_TYPE,
                             tags={},
                             rg_tags={"schedule-profile": "weekday-0830-1730"}))
    results = select_resources([rec], enabled_handler_keys=["vm"])
    assert results[0].eligible is True
    assert results[0].profile_name == "weekday-0830-1730"


def test_c2_profile_inherited_from_subscription_end_to_end():
    rec = _discover_one(_row(_VM_RID, _VM_TYPE,
                             tags={},
                             sub_tags={"schedule-profile": "sub-prof"}))
    results = select_resources([rec], enabled_handler_keys=["vm"])
    assert results[0].eligible is True
    assert results[0].profile_name == "sub-prof"


def test_c2_rg_override_tags_visible_end_to_end():
    # C2 / US-06: override tags set on the RG are now seen by the engine.
    rec = _discover_one(_row(_VM_RID, _VM_TYPE,
                             tags={},
                             rg_tags={
                                 "schedule-profile": "weekday-0830-1730",
                                 "schedule-override-state": "stopped",
                                 "schedule-override-until": "2026-10-10T21:00+07:00",
                             }))
    results = select_resources([rec], enabled_handler_keys=["vm"])
    assert results[0].eligible is True
    assert results[0].override_state == "stopped"
    assert results[0].override_until == "2026-10-10T21:00+07:00"


def test_c2_tag_precedence_resource_over_rg_over_sub_end_to_end():
    rec = _discover_one(_row(_VM_RID, _VM_TYPE,
                             tags={"schedule-profile": "res-prof"},
                             rg_tags={"schedule-profile": "rg-prof"},
                             sub_tags={"schedule-profile": "sub-prof"}))
    results = select_resources([rec], enabled_handler_keys=["vm"])
    assert results[0].eligible is True
    assert results[0].profile_name == "res-prof"
