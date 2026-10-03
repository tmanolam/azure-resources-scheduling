"""MySQL Flexible Server handler (T-302).

Handler key ``mysql-flex`` → ``Microsoft.DBforMySQL/flexibleServers`` (§8.1).

Mirrors the PostgreSQL Flexible Server handler:
- Start: ``servers.begin_start``; Stop: ``servers.begin_stop``.
- HR-003: platform auto-start after 7 days is corrected next cycle.
- HR-004: HA / replica rejection => HandlerSkip (log + skip + no retry).
"""

from __future__ import annotations

import logging

from engine.models import ResourceRecord

from .base import BaseHandler, HandlerSkip, parse_resource_name, register

logger = logging.getLogger("pwrsched.handlers.mysql_flex")

_HA_REPLICA_MARKERS = ("high availability", "high-availability", "replica", "read replica")


def _is_ha_or_replica_refusal(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(marker in msg for marker in _HA_REPLICA_MARKERS)


@register
class MysqlFlexHandler(BaseHandler):
    handler_key = "mysql-flex"

    def get_state(self, resource: ResourceRecord) -> str:
        client = self._client(resource)
        name = parse_resource_name(resource.resource_id)
        server = client.servers.get(resource.resource_group, name)
        return getattr(server, "state", "") or "unknown"

    def start(self, resource: ResourceRecord) -> None:
        self._invoke("begin_start", resource)

    def stop(self, resource: ResourceRecord) -> None:
        self._invoke("begin_stop", resource)

    def _invoke(self, method: str, resource: ResourceRecord) -> None:
        client = self._client(resource)
        name = parse_resource_name(resource.resource_id)
        try:
            getattr(client.servers, method)(resource.resource_group, name)
        except HandlerSkip:
            raise
        except Exception as exc:  # noqa: BLE001
            if _is_ha_or_replica_refusal(exc):  # HR-004
                raise HandlerSkip("mysql-ha-or-replica-rejected") from exc
            raise
