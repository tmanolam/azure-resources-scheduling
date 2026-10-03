"""Application Gateway handler (T-303, Could).

Handler key ``appgw`` → ``Microsoft.Network/applicationGateways`` (§8.1, order 2).

- Start: ``application_gateways.begin_start``.
- Stop:  ``application_gateways.begin_stop``.

Actual state is read from the gateway ``operational_state`` ('Running',
'Stopped', 'Starting', 'Stopping'); the engine normalises it.
"""

from __future__ import annotations

import logging

from engine.models import ResourceRecord

from .base import BaseHandler, parse_resource_name, register

logger = logging.getLogger("pwrsched.handlers.appgw")


@register
class AppGwHandler(BaseHandler):
    handler_key = "appgw"

    def get_state(self, resource: ResourceRecord) -> str:
        client = self._client(resource)
        name = parse_resource_name(resource.resource_id)
        gw = client.application_gateways.get(resource.resource_group, name)
        return getattr(gw, "operational_state", "") or "unknown"

    def start(self, resource: ResourceRecord) -> None:
        client = self._client(resource)
        name = parse_resource_name(resource.resource_id)
        client.application_gateways.begin_start(resource.resource_group, name)

    def stop(self, resource: ResourceRecord) -> None:
        client = self._client(resource)
        name = parse_resource_name(resource.resource_id)
        client.application_gateways.begin_stop(resource.resource_group, name)
