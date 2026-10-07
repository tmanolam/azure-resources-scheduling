"""Virtual Machine Scale Set handler (T-302, V2, V3).

Handler key ``vmss`` → ``Microsoft.Compute/virtualMachineScaleSets`` (§8.1).

- Start: ``virtual_machine_scale_sets.begin_start``.
- Stop:  ``virtual_machine_scale_sets.begin_deallocate`` (deallocate, not power-off).

State is derived from the **per-instance** power states, not the scale-set
resource. A Uniform-mode scale set's own instance view
(``virtual_machine_scale_sets.get_instance_view``) reports only provisioning
state and *statusesSummary* — it carries no ``PowerState/*`` status — so reading
it returned ``unknown`` for a perfectly healthy, running scale set (verification
issue V2). Power state lives on the individual VMs.

Orchestration mode matters (V3):

- **Uniform:** instances are read via ``virtual_machine_scale_set_vms``. We use
  ``list(expand="instanceView")`` so one call returns every member's power state
  (one call per cycle instead of 1 + N).
- **Flexible:** Azure does not expose members through
  ``virtual_machine_scale_set_vms``; members are ordinary VMs. Phase 1 does not
  support power-managing a Flexible scale set through this handler, so
  ``get_state`` raises ``HandlerSkip("vmss-flexible-unsupported")`` — logged as a
  skip, never counted as a failure, never retried (HR-008). To schedule those
  workloads, tag the member VMs (the ``vm`` handler acts on each), not the scale
  set. Do not tag both (HR-008).

Aggregation (across all instances, Uniform):

- any instance ``running``            → ``running``   (so a running VMSS is stopped)
- all instances ``deallocated``       → ``deallocated`` (already converged)
- all instances powered off (billed)  → ``stopped-allocated`` (needs deallocate, H4)
- no instances readable, capacity 0   → ``deallocated`` (nothing is billed)
- no instances readable, capacity > 0 → ``unknown`` (likely missing the
  ``virtualMachineScaleSets/virtualMachines/read`` role action; the ARM instance
  list is authorization-filtered to empty rather than 403ing — finding V5. The
  engine logs ``unknown-state-skip`` and does not act, instead of wrongly
  reading the scale set as deallocated and re-submitting start every cycle.)
- any instance in a transitional state (``starting``/``deallocating``/…) and
  none running → that transitional state (engine skips & retries, FR-033)
- cannot determine                    → ``unknown`` (engine logs unknown-state-skip)
"""

from __future__ import annotations

import logging

from engine.models import ResourceRecord

from .base import BaseHandler, HandlerSkip, parse_resource_name, register

logger = logging.getLogger("pwrsched.handlers.vmss")

# Transitional power states we must not act on (FR-033); surfaced only when no
# instance is already running.
_TRANSITIONAL = {"starting", "stopping", "deallocating"}


def _instance_power_state(iv) -> str:
    """Extract the lowercase ``PowerState/*`` suffix from an instance view, or ''.

    ``iv`` may be an instance-view object (``.statuses``) or, with
    ``list(expand="instanceView")``, the instance itself carrying an
    ``.instance_view`` attribute.
    """
    statuses = getattr(iv, "statuses", None)
    if statuses is None:
        inner = getattr(iv, "instance_view", None)
        statuses = getattr(inner, "statuses", None) if inner is not None else None
    for status in statuses or []:
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

        # One scale-set read gives us both the orchestration mode (V3) and the
        # SKU capacity (number of instances), which we use below to tell a
        # genuinely scaled-to-zero scale set apart from an instance list that
        # came back empty because we lack permission to read it (finding V5).
        scale_set = self._get_scale_set(client, resource, name)
        mode = (getattr(scale_set, "orchestration_mode", "") or "").lower() if scale_set else ""

        # V3: Flexible scale sets don't expose members via scale_set_vms. Skip
        # (logged, not a failure); their member VMs are scheduled individually.
        if mode == "flexible":
            raise HandlerSkip("vmss-flexible-unsupported")

        vm_ops = client.virtual_machine_scale_set_vms

        # One call returns every member's instanceView (V3 cost fix); fall back to
        # per-instance get_instance_view if an instance view is not inlined.
        states: list[str] = []
        for inst in vm_ops.list(resource.resource_group, name, expand="instanceView"):
            ps = _instance_power_state(inst)
            if not ps:
                instance_id = getattr(inst, "instance_id", None)
                if instance_id is not None:
                    iv = vm_ops.get_instance_view(resource.resource_group, name, instance_id)
                    ps = _instance_power_state(iv)
            if ps:
                states.append(ps)

        if not states:
            # No instance power states. Two very different causes:
            #  - genuine capacity 0 (scaled to no instances): nothing is billed,
            #    which is the desired "stopped" outcome → deallocated (converged);
            #  - the instance list came back empty because the identity lacks
            #    Microsoft.Compute/virtualMachineScaleSets/virtualMachines/read
            #    (ARM authorization-filters the list to empty rather than 403ing).
            #    Reporting deallocated here would be wrong for a running scale set
            #    and makes the engine re-submit start every cycle (finding V5).
            # Use the SKU capacity to tell them apart: capacity > 0 but no states
            # read ⇒ we can't determine the state ⇒ unknown (engine skips & logs,
            # not a silent wrong action).
            capacity = self._capacity(scale_set)
            if capacity and capacity > 0:
                logger.warning(
                    "pwrsched.handlers.vmss: %s has capacity %s but no instance "
                    "power states were readable; reporting unknown (check the role "
                    "has Microsoft.Compute/virtualMachineScaleSets/virtualMachines/read)",
                    name, capacity,
                )
                return "unknown"
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

    @staticmethod
    def _get_scale_set(client, resource: ResourceRecord, name: str):
        """Return the scale set object (for orchestration mode + SKU capacity), or
        None if it cannot be read. A failure here is defensive: the caller treats
        an unknown mode as Uniform and an unknown capacity as 'can't tell'."""
        try:
            return client.virtual_machine_scale_sets.get(resource.resource_group, name)
        except Exception as exc:  # defensive: fall back to Uniform behaviour
            logger.warning("pwrsched.handlers.vmss: get() failed for %s: %s", name, exc)
            return None

    @staticmethod
    def _capacity(scale_set) -> int | None:
        """Return the scale set's SKU capacity (instance count), or None if it
        cannot be determined."""
        sku = getattr(scale_set, "sku", None) if scale_set is not None else None
        capacity = getattr(sku, "capacity", None) if sku is not None else None
        try:
            return int(capacity) if capacity is not None else None
        except (TypeError, ValueError):
            return None

    def start(self, resource: ResourceRecord) -> None:
        client = self._client(resource)
        name = parse_resource_name(resource.resource_id)
        client.virtual_machine_scale_sets.begin_start(resource.resource_group, name)

    def stop(self, resource: ResourceRecord) -> None:
        client = self._client(resource)
        name = parse_resource_name(resource.resource_id)
        client.virtual_machine_scale_sets.begin_deallocate(resource.resource_group, name)
