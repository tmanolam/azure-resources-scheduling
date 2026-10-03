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


def _row(rid, rtype, sub="s1", rg="rg1", tags=None):
    return {"id": rid, "type": rtype, "subscriptionId": sub, "resourceGroup": rg,
            "location": "southeastasia", "tags": tags or {"schedule-profile": "weekday-0830-1730"}}


def test_build_kql_includes_only_enabled_types():
    q = build_kql_query(["vm", "aks"])
    assert "microsoft.compute/virtualmachines" in q
    assert "microsoft.containerservice/managedclusters" in q
    assert "microsoft.dbformysql/flexibleservers" not in q
    assert "schedule-profile" in q  # opt-in pre-filter


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
