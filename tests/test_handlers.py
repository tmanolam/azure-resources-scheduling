"""Unit tests for resource handlers (T-301, T-302, T-303)."""

from __future__ import annotations

import os
import sys
import types

import pytest

_SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from engine.models import ResourceRecord  # noqa: E402
from engine.reconcile import _normalise_actual  # noqa: E402
from engine.models import ActualState  # noqa: E402
from handlers import _load_all_handlers  # noqa: E402
from handlers.base import (  # noqa: E402
    HandlerSkip,
    build_registry,
    parse_resource_name,
)
from handlers.vm import VmHandler  # noqa: E402
from handlers.vmss import VmssHandler  # noqa: E402
from handlers.aks import AksHandler  # noqa: E402
from handlers.postgres_flex import PostgresFlexHandler  # noqa: E402
from handlers.mysql_flex import MysqlFlexHandler  # noqa: E402
from handlers.sqlmi import SqlMiHandler  # noqa: E402
from handlers.appgw import AppGwHandler  # noqa: E402


def _ns(**kw):
    return types.SimpleNamespace(**kw)


def _rid(ns, rtype, name, rg="rg1", sub="s1"):
    return f"/subscriptions/{sub}/resourceGroups/{rg}/providers/{ns}/{rtype}/{name}"


def _rec(resource_id, handler_key, rtype):
    return ResourceRecord(resource_id=resource_id, resource_type=rtype,
                          handler_key=handler_key, subscription_id="s1", resource_group="rg1")


# --- T-301 base: id parsing + registry ---------------------------------------

def test_parse_resource_name():
    rid = _rid("Microsoft.Compute", "virtualMachines", "vm1")
    assert parse_resource_name(rid) == "vm1"


def test_parse_resource_name_invalid_raises():
    with pytest.raises(HandlerSkip):
        parse_resource_name("not-an-arm-id")


def test_build_registry_only_enabled_and_supplied():
    def factory(_sub):
        return object()

    reg = build_registry(["vm", "aks", "appgw"],
                         {"vm": factory, "aks": factory})  # appgw factory missing
    assert set(reg) == {"vm", "aks"}
    assert isinstance(reg["vm"], VmHandler)


def test_all_handlers_register():
    _load_all_handlers()
    from handlers.base import _REGISTRY
    for key in ["vm", "vmss", "aks", "postgres-flex", "mysql-flex", "sqlmi", "appgw"]:
        assert key in _REGISTRY


# --- VM (HR-001) -------------------------------------------------------------

class FakeVmOps:
    def __init__(self, power="running", ephemeral=False):
        self.power = power
        self.ephemeral = ephemeral
        self.calls = []

    def instance_view(self, rg, name):
        return _ns(statuses=[_ns(code="ProvisioningState/succeeded"),
                             _ns(code=f"PowerState/{self.power}")])

    def get(self, rg, name):
        diff = _ns() if self.ephemeral else None
        return _ns(storage_profile=_ns(os_disk=_ns(diff_disk_settings=diff)))

    def begin_start(self, rg, name):
        self.calls.append(("start", name))

    def begin_deallocate(self, rg, name):
        self.calls.append(("deallocate", name))


def _vm_client(ops):
    return _ns(virtual_machines=ops)


def test_vm_get_state_power_code():
    ops = FakeVmOps(power="running")
    h = VmHandler(lambda s: _vm_client(ops))
    rec = _rec(_rid("Microsoft.Compute", "virtualMachines", "vm1"), "vm", "Microsoft.Compute/virtualMachines")
    assert h.get_state(rec) == "running"
    assert _normalise_actual(h.get_state(rec)) is ActualState.RUNNING


def test_vm_stop_uses_deallocate():
    ops = FakeVmOps(power="running", ephemeral=False)
    h = VmHandler(lambda s: _vm_client(ops))
    rec = _rec(_rid("Microsoft.Compute", "virtualMachines", "vm1"), "vm", "Microsoft.Compute/virtualMachines")
    h.stop(rec)
    assert ops.calls == [("deallocate", "vm1")]  # HR-001: deallocate, not power off


def test_vm_ephemeral_os_disk_skipped_on_stop():
    ops = FakeVmOps(ephemeral=True)
    h = VmHandler(lambda s: _vm_client(ops))
    rec = _rec(_rid("Microsoft.Compute", "virtualMachines", "vm1"), "vm", "Microsoft.Compute/virtualMachines")
    with pytest.raises(HandlerSkip):
        h.stop(rec)
    assert ops.calls == []  # HR-001: never deallocated


# --- VMSS --------------------------------------------------------------------

def test_vmss_start_and_state():
    calls = []
    ops = _ns(
        get_instance_view=lambda rg, n: _ns(statuses=[_ns(code="PowerState/running")]),
        begin_start=lambda rg, n: calls.append(("start", n)),
        begin_deallocate=lambda rg, n: calls.append(("deallocate", n)),
    )
    h = VmssHandler(lambda s: _ns(virtual_machine_scale_sets=ops))
    rec = _rec(_rid("Microsoft.Compute", "virtualMachineScaleSets", "ss1"), "vmss", "Microsoft.Compute/virtualMachineScaleSets")
    assert h.get_state(rec) == "running"
    h.stop(rec)
    assert calls == [("deallocate", "ss1")]


# --- AKS (HR-002) ------------------------------------------------------------

def _aks_client(provisioning, power, calls):
    ops = _ns(
        get=lambda rg, n: _ns(provisioning_state=provisioning, power_state=_ns(code=power)),
        begin_start=lambda rg, n: calls.append(("start", n)),
        begin_stop=lambda rg, n: calls.append(("stop", n)),
    )
    return _ns(managed_clusters=ops)


def test_aks_state_running_when_succeeded():
    h = AksHandler(lambda s: _aks_client("Succeeded", "Running", []))
    rec = _rec(_rid("Microsoft.ContainerService", "managedClusters", "c1"), "aks", "Microsoft.ContainerService/managedClusters")
    assert h.get_state(rec) == "Running"


def test_aks_state_reports_provisioning_when_not_succeeded():
    # HR-002: not Succeeded => return provisioning state (engine treats as transitional/unknown).
    h = AksHandler(lambda s: _aks_client("Updating", "Running", []))
    rec = _rec(_rid("Microsoft.ContainerService", "managedClusters", "c1"), "aks", "Microsoft.ContainerService/managedClusters")
    assert h.get_state(rec) == "Updating"
    assert _normalise_actual(h.get_state(rec)) is ActualState.TRANSITIONAL


def test_aks_stop_blocked_when_not_succeeded():
    calls = []
    h = AksHandler(lambda s: _aks_client("Updating", "Running", calls))
    rec = _rec(_rid("Microsoft.ContainerService", "managedClusters", "c1"), "aks", "Microsoft.ContainerService/managedClusters")
    with pytest.raises(HandlerSkip):
        h.stop(rec)
    assert calls == []


def test_aks_start_when_succeeded():
    calls = []
    h = AksHandler(lambda s: _aks_client("Succeeded", "Stopped", calls))
    rec = _rec(_rid("Microsoft.ContainerService", "managedClusters", "c1"), "aks", "Microsoft.ContainerService/managedClusters")
    h.start(rec)
    assert calls == [("start", "c1")]


# --- Databases (HR-003 / HR-004) ---------------------------------------------

def _db_client(state, start_exc=None, stop_exc=None, calls=None):
    calls = calls if calls is not None else []

    def begin_start(rg, n):
        if start_exc:
            raise start_exc
        calls.append(("start", n))

    def begin_stop(rg, n):
        if stop_exc:
            raise stop_exc
        calls.append(("stop", n))

    return _ns(servers=_ns(get=lambda rg, n: _ns(state=state),
                           begin_start=begin_start, begin_stop=begin_stop)), calls


@pytest.mark.parametrize("Handler,ns,rtype", [
    (PostgresFlexHandler, "Microsoft.DBforPostgreSQL", "Microsoft.DBforPostgreSQL/flexibleServers"),
    (MysqlFlexHandler, "Microsoft.DBforMySQL", "Microsoft.DBforMySQL/flexibleServers"),
])
def test_db_ready_state_maps_running(Handler, ns, rtype):
    client, _ = _db_client("Ready")
    h = Handler(lambda s: client)
    rec = _rec(_rid(ns, "flexibleServers", "db1"), Handler.handler_key, rtype)
    assert h.get_state(rec) == "Ready"
    assert _normalise_actual(h.get_state(rec)) is ActualState.RUNNING


@pytest.mark.parametrize("Handler,ns,rtype", [
    (PostgresFlexHandler, "Microsoft.DBforPostgreSQL", "Microsoft.DBforPostgreSQL/flexibleServers"),
    (MysqlFlexHandler, "Microsoft.DBforMySQL", "Microsoft.DBforMySQL/flexibleServers"),
])
def test_db_stop_success(Handler, ns, rtype):
    client, calls = _db_client("Ready")
    h = Handler(lambda s: client)
    rec = _rec(_rid(ns, "flexibleServers", "db1"), Handler.handler_key, rtype)
    h.stop(rec)
    assert calls == [("stop", "db1")]


@pytest.mark.parametrize("Handler,ns,rtype", [
    (PostgresFlexHandler, "Microsoft.DBforPostgreSQL", "Microsoft.DBforPostgreSQL/flexibleServers"),
    (MysqlFlexHandler, "Microsoft.DBforMySQL", "Microsoft.DBforMySQL/flexibleServers"),
])
def test_db_ha_rejection_skips_no_retry(Handler, ns, rtype):
    # HR-004: platform rejects stop for HA server => HandlerSkip.
    client, _ = _db_client("Ready", stop_exc=RuntimeError("Stop not allowed: High Availability enabled"))
    h = Handler(lambda s: client)
    rec = _rec(_rid(ns, "flexibleServers", "db1"), Handler.handler_key, rtype)
    with pytest.raises(HandlerSkip):
        h.stop(rec)


@pytest.mark.parametrize("Handler,ns,rtype", [
    (PostgresFlexHandler, "Microsoft.DBforPostgreSQL", "Microsoft.DBforPostgreSQL/flexibleServers"),
    (MysqlFlexHandler, "Microsoft.DBforMySQL", "Microsoft.DBforMySQL/flexibleServers"),
])
def test_db_other_error_propagates(Handler, ns, rtype):
    # A non-HA error is not swallowed as a skip; it propagates (engine marks failed).
    client, _ = _db_client("Ready", stop_exc=RuntimeError("transient gateway timeout"))
    h = Handler(lambda s: client)
    rec = _rec(_rid(ns, "flexibleServers", "db1"), Handler.handler_key, rtype)
    with pytest.raises(RuntimeError):
        h.stop(rec)


# --- SQL MI ------------------------------------------------------------------

def test_sqlmi_stop_and_rejection():
    calls = []
    ops = _ns(
        get=lambda rg, n: _ns(state="Ready"),
        begin_start=lambda rg, n: calls.append(("start", n)),
        begin_stop=lambda rg, n: calls.append(("stop", n)),
    )
    h = SqlMiHandler(lambda s: _ns(managed_instances=ops))
    rec = _rec(_rid("Microsoft.Sql", "managedInstances", "mi1"), "sqlmi", "Microsoft.Sql/managedInstances")
    assert h.get_state(rec) == "Ready"
    h.stop(rec)
    assert calls == [("stop", "mi1")]


def test_sqlmi_rejection_skips():
    def begin_stop(rg, n):
        raise RuntimeError("Operation not supported for this instance")
    ops = _ns(get=lambda rg, n: _ns(state="Ready"), begin_start=lambda rg, n: None, begin_stop=begin_stop)
    h = SqlMiHandler(lambda s: _ns(managed_instances=ops))
    rec = _rec(_rid("Microsoft.Sql", "managedInstances", "mi1"), "sqlmi", "Microsoft.Sql/managedInstances")
    with pytest.raises(HandlerSkip):
        h.stop(rec)


# --- App Gateway (T-303) -----------------------------------------------------

def test_appgw_start_stop_state():
    calls = []
    ops = _ns(
        get=lambda rg, n: _ns(operational_state="Running"),
        begin_start=lambda rg, n: calls.append(("start", n)),
        begin_stop=lambda rg, n: calls.append(("stop", n)),
    )
    h = AppGwHandler(lambda s: _ns(application_gateways=ops))
    rec = _rec(_rid("Microsoft.Network", "applicationGateways", "gw1"), "appgw", "Microsoft.Network/applicationGateways")
    assert h.get_state(rec) == "Running"
    assert _normalise_actual(h.get_state(rec)) is ActualState.RUNNING
    h.stop(rec)
    assert calls == [("stop", "gw1")]
