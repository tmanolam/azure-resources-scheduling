"""SQL Managed Instance handler (T-302).

Handler key ``sqlmi`` → ``Microsoft.Sql/managedInstances`` (§8.1, decision D-04).

- Start: ``managed_instances.begin_start``.
- Stop:  ``managed_instances.begin_stop``.
- HR-004: where the platform rejects stop/start (e.g. unsupported configuration),
  raise HandlerSkip (log + skip + no retry until configuration changes).

The managed instance exposes a start/stop capability on recent API versions. The
instance ``state`` (e.g. 'Ready', 'Stopped', 'Stopping', 'Starting') is read for
the actual state; the engine normalises it.
"""

from __future__ import annotations

import logging

from engine.models import ResourceRecord

from .base import BaseHandler, HandlerSkip, parse_resource_name, register

logger = logging.getLogger("pwrsched.handlers.sqlmi")

_REJECTION_MARKERS = (
    "not supported", "cannot be stopped", "cannot be started", "not allowed", "invalid state"
)


def _is_rejection(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(marker in msg for marker in _REJECTION_MARKERS)


@register
class SqlMiHandler(BaseHandler):
    handler_key = "sqlmi"

    def get_state(self, resource: ResourceRecord) -> str:
        client = self._client(resource)
        name = parse_resource_name(resource.resource_id)
        mi = client.managed_instances.get(resource.resource_group, name)
        return getattr(mi, "state", "") or "unknown"

    def start(self, resource: ResourceRecord) -> None:
        self._invoke("begin_start", resource)

    def stop(self, resource: ResourceRecord) -> None:
        self._invoke("begin_stop", resource)

    def _invoke(self, method: str, resource: ResourceRecord) -> None:
        client = self._client(resource)
        name = parse_resource_name(resource.resource_id)
        try:
            getattr(client.managed_instances, method)(resource.resource_group, name)
        except HandlerSkip:
            raise
        except Exception as exc:  # noqa: BLE001
            if _is_rejection(exc):  # HR-004
                raise HandlerSkip("sqlmi-operation-rejected") from exc
            raise
