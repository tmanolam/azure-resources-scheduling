"""Virtual Machine Scale Set handler (T-302).

Handler key ``vmss`` → ``Microsoft.Compute/virtualMachineScaleSets`` (§8.1).

- Start: ``virtual_machine_scale_sets.begin_start``.
- Stop:  ``virtual_machine_scale_sets.begin_deallocate`` (deallocate, not power-off).

State is derived from the **per-instance** power states, not the scale-set
resource. A Uniform-mode scale set's own instance view
(``virtual_machine_scale_sets.get_instance_view``) reports only provisioning
state and *statusesSummary* — it carries no ``PowerState/*`` status — so reading
it returned ``unknown`` for a perfectly healthy, running scale set (verification
issue V2). Power state lives on the individual VMs, read via
``virtual_machine_scale_set_vms``.

Aggregation (across all instances):

- any instance ``running``            → ``running``   (so a running VMSS is stopped)
- all instances ``deallocated``       → ``deallocated`` (already converged)
- all instances powered off (billed)  → ``stopped-allocated`` (needs deallocate, H4)
- no instances at all (capacity 0)    → ``deallocated`` (nothing is billed)
- any instance in a transitional state (``starting``/``deallocating``/…) and
  none running → that transitional state (engine skips & retries, FR-033)
- cannot determine                    → ``unknown`` (engine logs unknown-state-skip)
"""

from __future__ import annotations

import logging

from engine.models import ResourceRecord

from .base import BaseHandler, parse_resource_name, register

logger = logging.getLogger("pwrsched.handlers.vmss")

# Transitional power states we must not act on (FR-033); surfaced only when no
# instance is already running.
_TRANSITIONAL = {"starting", "stopping", "deallocating"}


def _instance_power_state(iv) -> str:
    """Extract the lowercase ``PowerState/*`` suffix from an instance view, or ''."""
    for status in getattr(iv, "statuses", None) or []:
        code = getattr(status, "code", "") or ""
        if code.lower().startswith("powerstate/"):
            return code.split("/", 1)[1].lower()
    return ""


@register
class VmssHandler(BaseHandler):
    handler_key = "vmss"

    def get_state(self, resource: ResourceRecord) -> str:
        client = self._client(resource)
        name = parse_resource_name(resource.resource_id)
        vm_ops = client.virtual_machine_scale_set_vms

        states: list[str] = []
        for inst in vm_ops.list(resource.resource_group, name):
            instance_id = getattr(inst, "instance_id", None)
            if instance_id is None:
                continue
            iv = vm_ops.get_instance_view(resource.resource_group, name, instance_id)
            ps = _instance_power_state(iv)
            if ps:
                states.append(ps)

        if not states:
            # Capacity 0 (scaled to no instances): nothing is allocated or billed,
            # which is the desired "stopped" outcome. Treat as deallocated so the
            # engine converges instead of logging unknown-state-skip.
            return "deallocated"

        # Any running instance => the scale set is effectively running and, if the
        # desired state is Stopped, must be deallocated.
        if any(s == "running" for s in states):
            return "running"

        # No running instances: surface a transitional state so the engine skips
        # and retries next cycle (FR-033).
        transitional = next((s for s in states if s in _TRANSITIONAL), None)
        if transitional:
            return transitional

        # All instances off. "stopped" means powered off but still allocated/billed
        # => report stopped-allocated so the engine deallocates (H4). If every
        # instance is already deallocated, we're converged.
        if all(s == "deallocated" for s in states):
            return "deallocated"
        return "stopped-allocated"

    def start(self, resource: ResourceRecord) -> None:
        client = self._client(resource)
        name = parse_resource_name(resource.resource_id)
        client.virtual_machine_scale_sets.begin_start(resource.resource_group, name)

    def stop(self, resource: ResourceRecord) -> None:
        client = self._client(resource)
        name = parse_resource_name(resource.resource_id)
        client.virtual_machine_scale_sets.begin_deallocate(resource.resource_group, name)
