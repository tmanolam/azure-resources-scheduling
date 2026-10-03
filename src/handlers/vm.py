"""Virtual Machine handler (T-302).

Handler key ``vm`` → ``Microsoft.Compute/virtualMachines`` (§8.1).

- Start: ``virtual_machines.begin_start``.
- Stop:  ``virtual_machines.begin_deallocate`` (HR-001: deallocate, not power-off,
  so compute is not billed).
- HR-001: VMs with an ephemeral OS disk cannot be deallocated; they are skipped
  and logged as unsupported.

State is read from the instance view power-state code (e.g. ``PowerState/running``,
``PowerState/deallocated``, ``PowerState/stopping``). The injected client is any
object exposing ``.virtual_machines`` with the methods used here (the real
``azure.mgmt.compute.ComputeManagementClient`` satisfies this).
"""

from __future__ import annotations

import logging

from engine.models import ResourceRecord

from .base import BaseHandler, HandlerSkip, parse_resource_name, register

logger = logging.getLogger("pwrsched.handlers.vm")


@register
class VmHandler(BaseHandler):
    handler_key = "vm"

    def get_state(self, resource: ResourceRecord) -> str:
        client = self._client(resource)
        name = parse_resource_name(resource.resource_id)
        iv = client.virtual_machines.instance_view(resource.resource_group, name)
        for status in getattr(iv, "statuses", None) or []:
            code = getattr(status, "code", "") or ""
            if code.lower().startswith("powerstate/"):
                state = code.split("/", 1)[1].lower()  # 'running', 'deallocated', 'stopped', ...
                # 'stopped' = powered off from inside the OS but still allocated
                # and billed; it must still be deallocated (HR-001, H4). Signal a
                # distinct state so the engine does not treat it as converged.
                if state == "stopped":
                    return "stopped-allocated"
                return state
        return "unknown"

    def _is_ephemeral_os_disk(self, resource: ResourceRecord) -> bool:
        client = self._client(resource)
        name = parse_resource_name(resource.resource_id)
        vm = client.virtual_machines.get(resource.resource_group, name)
        os_disk = getattr(getattr(getattr(vm, "storage_profile", None), "os_disk", None), "diff_disk_settings", None)
        return os_disk is not None

    def start(self, resource: ResourceRecord) -> None:
        client = self._client(resource)
        name = parse_resource_name(resource.resource_id)
        client.virtual_machines.begin_start(resource.resource_group, name)

    def stop(self, resource: ResourceRecord) -> None:
        if self._is_ephemeral_os_disk(resource):
            raise HandlerSkip("vm-ephemeral-os-disk-unsupported")  # HR-001
        client = self._client(resource)
        name = parse_resource_name(resource.resource_id)
        client.virtual_machines.begin_deallocate(resource.resource_group, name)  # HR-001
