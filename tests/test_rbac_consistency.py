"""Role/SDK consistency: every Azure call a handler makes must be allowed by the
custom role (SEC-002).

Lesson from finding V5: the V2 fix changed which Azure API the ``vmss`` handler
calls (per-instance reads), but the role in ``infra/modules/rbac`` was not
updated. ARM authorization-filtered the instance list to empty instead of
returning 403, so nothing failed visibly and the scale set was re-started every
cycle. This test fails as soon as a handler calls an SDK operation that is either
unmapped here or not granted by the role, so the two cannot drift apart again.

How it works:
1. Statically scan each handler module (AST) for management-client calls:
   ``client.<ops>.<method>(...)``, aliases such as ``vm_ops = client.<ops>`` and
   the ``getattr(client.<ops>, method)`` + ``self._invoke("<method>")`` pattern.
   A static scan also covers rarely-taken branches (for example the vmss
   per-instance fallback) that a mock-driven test would miss.
2. Map each (operations group, method) to the ARM action it needs
   (``REQUIRED_ACTIONS``).
3. Parse ``actions_by_handler`` from ``infra/modules/rbac/main.tf`` and assert
   every required action is granted for that handler.

When adding a handler or a new SDK call: add the mapping below **and** the
action to the role (and REQUIREMENTS §11.1).
"""

from __future__ import annotations

import ast
import os
import re

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_HANDLERS_DIR = os.path.join(_ROOT, "src", "handlers")
_RBAC_TF = os.path.join(_ROOT, "infra", "modules", "rbac", "main.tf")

# handler key -> source module file
HANDLER_MODULES = {
    "vm": "vm.py",
    "vmss": "vmss.py",
    "aks": "aks.py",
    "postgres-flex": "postgres_flex.py",
    "mysql-flex": "mysql_flex.py",
    "sqlmi": "sqlmi.py",
    "appgw": "appgw.py",
}

_VM = "Microsoft.Compute/virtualMachines"
_VMSS = "Microsoft.Compute/virtualMachineScaleSets"

# handler key -> {(operations group, method): required ARM action}
REQUIRED_ACTIONS: dict[str, dict[tuple[str, str], str]] = {
    "vm": {
        ("virtual_machines", "get"): f"{_VM}/read",
        ("virtual_machines", "instance_view"): f"{_VM}/instanceView/read",
        ("virtual_machines", "begin_start"): f"{_VM}/start/action",
        ("virtual_machines", "begin_deallocate"): f"{_VM}/deallocate/action",
    },
    "vmss": {
        ("virtual_machine_scale_sets", "get"): f"{_VMSS}/read",
        ("virtual_machine_scale_sets", "get_instance_view"): f"{_VMSS}/instanceView/read",
        ("virtual_machine_scale_sets", "begin_start"): f"{_VMSS}/start/action",
        ("virtual_machine_scale_sets", "begin_deallocate"): f"{_VMSS}/deallocate/action",
        ("virtual_machine_scale_set_vms", "list"): f"{_VMSS}/virtualMachines/read",
        ("virtual_machine_scale_set_vms", "get"): f"{_VMSS}/virtualMachines/read",
        ("virtual_machine_scale_set_vms", "get_instance_view"):
            f"{_VMSS}/virtualMachines/instanceView/read",
    },
    "aks": {
        ("managed_clusters", "get"): "Microsoft.ContainerService/managedClusters/read",
        ("managed_clusters", "begin_start"): "Microsoft.ContainerService/managedClusters/start/action",
        ("managed_clusters", "begin_stop"): "Microsoft.ContainerService/managedClusters/stop/action",
    },
    "postgres-flex": {
        ("servers", "get"): "Microsoft.DBforPostgreSQL/flexibleServers/read",
        ("servers", "begin_start"): "Microsoft.DBforPostgreSQL/flexibleServers/start/action",
        ("servers", "begin_stop"): "Microsoft.DBforPostgreSQL/flexibleServers/stop/action",
    },
    "mysql-flex": {
        ("servers", "get"): "Microsoft.DBforMySQL/flexibleServers/read",
        ("servers", "begin_start"): "Microsoft.DBforMySQL/flexibleServers/start/action",
        ("servers", "begin_stop"): "Microsoft.DBforMySQL/flexibleServers/stop/action",
    },
    "sqlmi": {
        ("managed_instances", "get"): "Microsoft.Sql/managedInstances/read",
        ("managed_instances", "begin_start"): "Microsoft.Sql/managedInstances/start/action",
        ("managed_instances", "begin_stop"): "Microsoft.Sql/managedInstances/stop/action",
    },
    "appgw": {
        ("application_gateways", "get"): "Microsoft.Network/applicationGateways/read",
        ("application_gateways", "begin_start"): "Microsoft.Network/applicationGateways/start/action",
        ("application_gateways", "begin_stop"): "Microsoft.Network/applicationGateways/stop/action",
    },
}


def _sdk_calls(path: str) -> set[tuple[str, str]]:
    """Return the (operations group, method) pairs a handler module calls."""
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=path)

    def client_ops(node: ast.AST) -> str | None:
        # client.<ops>  (the management client is always bound to `client`)
        if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
                and node.value.id == "client"):
            return node.attr
        return None

    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            ops = client_ops(node.value)
            if isinstance(target, ast.Name) and ops:
                aliases[target.id] = ops

    calls: set[tuple[str, str]] = set()
    dynamic_ops: set[str] = set()
    invoked_methods: set[str] = set()

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        # client.<ops>.<method>(...)  or  <alias>.<method>(...)
        if isinstance(func, ast.Attribute):
            ops = client_ops(func.value)
            if ops is None and isinstance(func.value, ast.Name):
                ops = aliases.get(func.value.id)
            if ops:
                calls.add((ops, func.attr))
            # self._invoke("<method>", ...)
            if (func.attr == "_invoke" and isinstance(func.value, ast.Name)
                    and func.value.id == "self" and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)):
                invoked_methods.add(node.args[0].value)
        # getattr(client.<ops>, method)(...)
        if (isinstance(func, ast.Call) and isinstance(func.func, ast.Name)
                and func.func.id == "getattr" and func.args):
            ops = client_ops(func.args[0])
            if ops:
                dynamic_ops.add(ops)

    for ops in dynamic_ops:
        for method in invoked_methods:
            calls.add((ops, method))
    return calls


def _role_actions_by_handler() -> dict[str, set[str]]:
    """Parse ``actions_by_handler`` from the rbac module."""
    with open(_RBAC_TF, encoding="utf-8") as f:
        text = f.read()
    block = text[text.index("actions_by_handler"):]
    result: dict[str, set[str]] = {}
    for m in re.finditer(r'^\s*"?([a-z][a-z0-9-]*)"?\s*=\s*\[(.*?)\]', block, re.S | re.M):
        key, body = m.group(1), m.group(2)
        if key not in HANDLER_MODULES:
            continue
        result[key] = set(re.findall(r'"(Microsoft\.[^"]+)"', body))
    return result


ROLE = _role_actions_by_handler()


def test_every_handler_module_is_covered():
    """New handler files must be added to this test (and to the role)."""
    files = {f for f in os.listdir(_HANDLERS_DIR)
             if f.endswith(".py") and f not in ("__init__.py", "base.py")}
    assert files == set(HANDLER_MODULES.values()), (
        "Handler modules changed; update HANDLER_MODULES and REQUIRED_ACTIONS "
        f"in this test. Found: {sorted(files)}")


def test_every_handler_has_a_role_entry():
    missing = set(HANDLER_MODULES) - set(ROLE)
    assert not missing, f"No actions_by_handler entry in infra/modules/rbac for: {sorted(missing)}"


@pytest.mark.parametrize("key", sorted(HANDLER_MODULES))
def test_handler_sdk_calls_are_mapped_and_granted(key):
    calls = _sdk_calls(os.path.join(_HANDLERS_DIR, HANDLER_MODULES[key]))
    assert calls, f"{key}: no SDK calls detected; the scan pattern may need updating"

    unmapped = sorted(c for c in calls if c not in REQUIRED_ACTIONS[key])
    assert not unmapped, (
        f"{key}: SDK calls with no required-action mapping: {unmapped}. Add them to "
        "REQUIRED_ACTIONS and grant the action in infra/modules/rbac (REQUIREMENTS §11.1).")

    missing = sorted({REQUIRED_ACTIONS[key][c] for c in calls} - ROLE[key])
    assert not missing, (
        f"{key}: the handler calls operations whose actions are not in the custom role: "
        f"{missing}. Add them to actions_by_handler in infra/modules/rbac/main.tf.")


def test_scan_detects_known_calls():
    """Guard the scanner itself against silently matching nothing."""
    vmss = _sdk_calls(os.path.join(_HANDLERS_DIR, "vmss.py"))
    assert ("virtual_machine_scale_set_vms", "list") in vmss          # alias pattern
    assert ("virtual_machine_scale_sets", "begin_deallocate") in vmss  # direct pattern
    pg = _sdk_calls(os.path.join(_HANDLERS_DIR, "postgres_flex.py"))
    assert ("servers", "begin_stop") in pg                            # _invoke pattern
