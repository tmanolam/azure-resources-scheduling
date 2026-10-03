"""Virtual Machine Scale Set handler (T-302).

Handler key ``vmss`` → ``Microsoft.Compute/virtualMachineScaleSets`` (§8.1).

- Start: ``virtual_machine_scale_sets.begin_start``.
- Stop:  ``virtual_machine_scale_sets.begin_deallocate`` (deallocate, not power-off).

State is derived from the scale set instance view's VM power-state summary.
"""

from __future__ import annotations

import logging

from engine.models import ResourceRecord

from .base import BaseHandler, parse_resource_name, register

logger = logging.getLogger("pwrsched.handlers.vmss")


@register
class VmssHandler(BaseHandler):
    handler_key = "vmss"

    def get_state(self, resource: ResourceRecord) -> str:
        client = self._client(resource)
        name = parse_resource_name(resource.resource_id)
        iv = client.virtual_machine_scale_sets.get_instance_view(resource.resource_group, name)
        for status in getattr(iv, "statuses", None) or []:
            code = getattr(status, "code", "") or ""
            if code.lower().startswith("powerstate/"):
                return code.split("/", 1)[1]
        return "unknown"

    def start(self, resource: ResourceRecord) -> None:
        client = self._client(resource)
        name = parse_resource_name(resource.resource_id)
        client.virtual_machine_scale_sets.begin_start(resource.resource_group, name)

    def stop(self, resource: ResourceRecord) -> None:
        client = self._client(resource)
        name = parse_resource_name(resource.resource_id)
        client.virtual_machine_scale_sets.begin_deallocate(resource.resource_group, name)
