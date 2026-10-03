"""Azure Kubernetes Service handler (T-302).

Handler key ``aks`` → ``Microsoft.ContainerService/managedClusters`` (§8.1).

- Start: ``managed_clusters.begin_start``.
- Stop:  ``managed_clusters.begin_stop``.
- HR-002: read ``powerState.code`` and act only when the cluster
  ``provisioningState`` is ``Succeeded``; otherwise skip (a start/stop is
  already in progress or the cluster is being updated).
"""

from __future__ import annotations

import logging

from engine.models import ResourceRecord

from .base import BaseHandler, HandlerSkip, parse_resource_name, register

logger = logging.getLogger("pwrsched.handlers.aks")


@register
class AksHandler(BaseHandler):
    handler_key = "aks"

    def _get_cluster(self, resource: ResourceRecord):
        client = self._client(resource)
        name = parse_resource_name(resource.resource_id)
        return client.managed_clusters.get(resource.resource_group, name)

    def get_state(self, resource: ResourceRecord) -> str:
        cluster = self._get_cluster(resource)
        provisioning = (getattr(cluster, "provisioning_state", "") or "")
        if provisioning.lower() != "succeeded":
            # Transitional provisioning => engine skips (FR-033).
            return provisioning or "unknown"
        power = getattr(cluster, "power_state", None)
        code = getattr(power, "code", "") or ""
        # AKS power codes: 'Running' / 'Stopped'.
        return code or "unknown"

    def start(self, resource: ResourceRecord) -> None:
        self._guard_succeeded(resource)
        client = self._client(resource)
        name = parse_resource_name(resource.resource_id)
        client.managed_clusters.begin_start(resource.resource_group, name)

    def stop(self, resource: ResourceRecord) -> None:
        self._guard_succeeded(resource)
        client = self._client(resource)
        name = parse_resource_name(resource.resource_id)
        client.managed_clusters.begin_stop(resource.resource_group, name)

    def _guard_succeeded(self, resource: ResourceRecord) -> None:
        cluster = self._get_cluster(resource)
        provisioning = (getattr(cluster, "provisioning_state", "") or "").lower()
        if provisioning != "succeeded":  # HR-002
            raise HandlerSkip(f"aks-provisioning-{provisioning or 'unknown'}")
