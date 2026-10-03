"""PostgreSQL Flexible Server handler (T-302).

Handler key ``postgres-flex`` → ``Microsoft.DBforPostgreSQL/flexibleServers`` (§8.1).

- Start: ``servers.begin_start``.
- Stop:  ``servers.begin_stop``.
- HR-003: the platform auto-starts a stopped server after 7 days; reconciliation
  re-stops it when the desired state is Stopped (handled by the engine simply
  observing it running again and issuing stop next cycle).
- HR-004: HA / read-replica servers may reject stop/start. On such a rejection
  the handler raises HandlerSkip (log + skip + no retry until config changes).

Server ``state`` values: 'Ready' (running), 'Stopped', 'Starting', 'Stopping',
'Disabled', 'Updating'. The engine normalises these.
"""

from __future__ import annotations

import logging

from engine.models import ResourceRecord

from .base import BaseHandler, HandlerSkip, parse_resource_name, register

logger = logging.getLogger("pwrsched.handlers.postgres_flex")

# Substrings in an ARM error that indicate an HA/replica configuration refusal.
_HA_REPLICA_MARKERS = ("high availability", "high-availability", "replica", "read replica")


def _is_ha_or_replica_refusal(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(marker in msg for marker in _HA_REPLICA_MARKERS)


@register
class PostgresFlexHandler(BaseHandler):
    handler_key = "postgres-flex"

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
                raise HandlerSkip("postgres-ha-or-replica-rejected") from exc
            raise
