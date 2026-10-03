"""SDK-surface smoke test (finding C3).

Each resource handler calls specific operation-group methods on its Azure
management client (e.g. ``managed_instances.begin_start``). A version mismatch
in ``requirements.txt`` can silently drop a method, which only surfaces at
runtime as an ``AttributeError`` recorded as a failed action every cycle — this
is exactly how C3 (``azure-mgmt-sql==3.0.1`` lacking SQL MI start/stop) slipped
through.

This test asserts, for every handler, that the operation group its client
exposes actually has the methods the handler invokes. It is a *surface* check:
it instantiates the client without credentials and introspects attributes; it
makes no network calls.

The Azure SDKs are optional for the pure-engine unit tests, so when a client
package is not installed the individual assertion is skipped. In CI the Function
App ``requirements.txt`` is installed, so the full matrix runs and would fail if
a pinned version does not expose a required method.
"""

from __future__ import annotations

import importlib
import os
import sys

import pytest

_SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

# (handler key, client module, client class, operation-group attr, [methods])
_SURFACE = [
    (
        "vm",
        "azure.mgmt.compute",
        "ComputeManagementClient",
        "virtual_machines",
        ["get", "instance_view", "begin_start", "begin_deallocate"],
    ),
    (
        "vmss",
        "azure.mgmt.compute",
        "ComputeManagementClient",
        "virtual_machine_scale_sets",
        ["get_instance_view", "begin_start", "begin_deallocate"],
    ),
    (
        "aks",
        "azure.mgmt.containerservice",
        "ContainerServiceClient",
        "managed_clusters",
        ["get", "begin_start", "begin_stop"],
    ),
    (
        "postgres-flex",
        "azure.mgmt.rdbms.postgresql_flexibleservers",
        "PostgreSQLManagementClient",
        "servers",
        ["get", "begin_start", "begin_stop"],
    ),
    (
        "mysql-flex",
        "azure.mgmt.rdbms.mysql_flexibleservers",
        "MySQLManagementClient",
        "servers",
        ["get", "begin_start", "begin_stop"],
    ),
    (
        "sqlmi",
        "azure.mgmt.sql",
        "SqlManagementClient",
        "managed_instances",
        ["get", "begin_start", "begin_stop"],
    ),
    (
        "appgw",
        "azure.mgmt.network",
        "NetworkManagementClient",
        "application_gateways",
        ["get", "begin_start", "begin_stop"],
    ),
]


class _NoAuthCredential:
    """A credential stub; the surface check never requests a token."""

    def get_token(self, *scopes, **kwargs):  # pragma: no cover - never called
        raise AssertionError("surface test must not request a token")


def _make_client(module_name: str, class_name: str):
    module = importlib.import_module(module_name)
    client_cls = getattr(module, class_name)
    # Management clients build operation groups lazily from the subscription;
    # no network call happens at construction or on attribute access.
    return client_cls(credential=_NoAuthCredential(), subscription_id="00000000-0000-0000-0000-000000000000")


def _top_level_installed(module_name: str) -> bool:
    """True if the top-level distribution package appears to be installed.

    Distinguishes "SDK not installed" (legitimate skip in the engine-only dev
    environment) from "SDK installed but import/surface is broken" (a real
    failure we must surface, e.g. a bad pin).
    """
    top = module_name.split(".")[0]
    try:
        return importlib.util.find_spec(top) is not None
    except (ImportError, ValueError):
        return False


@pytest.mark.parametrize(
    "handler_key,module_name,class_name,op_group,methods",
    _SURFACE,
    ids=[row[0] for row in _SURFACE],
)
def test_handler_client_exposes_required_methods(
    handler_key, module_name, class_name, op_group, methods
):
    if not _top_level_installed(module_name):
        pytest.skip(f"{module_name} not installed; skipping surface check for {handler_key}")

    # Installed but broken import (e.g. wrong pin / missing transitive dep) is a
    # real failure, not a skip.
    client = _make_client(module_name, class_name)

    group = getattr(client, op_group, None)
    assert group is not None, f"{class_name} has no operation group '{op_group}' ({handler_key})"

    missing = [m for m in methods if not hasattr(group, m)]
    assert not missing, (
        f"{handler_key}: {class_name}.{op_group} is missing {missing}; "
        f"check the pinned version in src/requirements.txt"
    )
