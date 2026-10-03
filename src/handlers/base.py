"""Common resource-type handler interface and registry (T-301).

Every supported Azure resource type is handled by a module implementing the
common interface (``get_state``, ``start``, ``stop``) so new types can be added
without touching the engine (HR-005, NFR-007). Handlers are registered by their
handler key and resolved by the engine via :func:`build_registry`.

Design for testability:

- Handlers never construct Azure SDK clients themselves. They receive an
  injected ``client_factory`` — a callable ``(subscription_id) -> client`` —
  so unit tests pass fakes and no network/credential is required.
- State is returned as free text; the engine normalises it (see
  ``engine.reconcile._normalise_actual``). Handlers raise :class:`HandlerSkip`
  to signal "skip and do not retry until configuration changes" (HR-004).
  HTTP 429 throttling is handled by the Azure SDK's own retry policy
  (configured in ``runtime``), not by the handlers (M3).
"""

from __future__ import annotations

import logging
import re
from abc import ABC, abstractmethod
from typing import Callable, Mapping

from engine.models import ResourceRecord

__all__ = [
    "BaseHandler",
    "HandlerSkip",
    "ClientFactory",
    "parse_resource_name",
    "register",
    "build_registry",
    "DEFAULT_ORDER_BY_HANDLER",
]

logger = logging.getLogger("pwrsched.handlers")

# Factory signature: given a subscription id, return a configured ARM client.
ClientFactory = Callable[[str], object]

# Default start order per handler key (§8.1).
DEFAULT_ORDER_BY_HANDLER: dict[str, int] = {
    "postgres-flex": 1, "mysql-flex": 1, "sqlmi": 1, "synapse-pool": 1,
    "aks": 2, "appgw": 2,
    "vm": 3, "vmss": 3,
}


class HandlerSkip(Exception):
    """Raised by a handler to skip a resource without retrying (HR-001, HR-004).

    Example causes: VM with an ephemeral OS disk (unsupported stop), or a
    database the platform refuses to stop/start due to HA/replica config. The
    engine logs the reason and does not act on the resource this cycle.
    """

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


# ARM id: /subscriptions/<s>/resourceGroups/<rg>/providers/<ns>/<type>/<name>[/...]
_NAME_RE = re.compile(
    r"/subscriptions/[^/]+/resourceGroups/[^/]+/providers/[^/]+/[^/]+/(?P<name>[^/]+)",
    re.IGNORECASE,
)


def parse_resource_name(resource_id: str) -> str:
    """Extract the resource name (first name segment) from an ARM resource id."""
    m = _NAME_RE.search(resource_id or "")
    if not m:
        raise HandlerSkip(f"unparseable resource id: {resource_id!r}")
    return m.group("name")


class BaseHandler(ABC):
    """Base class for resource-type handlers.

    Subclasses set ``handler_key`` and implement ``get_state``/``start``/``stop``.
    The ``client_factory`` yields an ARM client scoped to a subscription.
    """

    handler_key: str = ""

    def __init__(self, client_factory: ClientFactory):
        self._client_factory = client_factory

    def _client(self, resource: ResourceRecord):
        return self._client_factory(resource.subscription_id)

    @abstractmethod
    def get_state(self, resource: ResourceRecord) -> str:
        """Return the resource's current power state as free text."""

    @abstractmethod
    def start(self, resource: ResourceRecord) -> None:
        """Submit a start operation (asynchronous; do not wait — FR-005)."""

    @abstractmethod
    def stop(self, resource: ResourceRecord) -> None:
        """Submit a stop/deallocate/pause operation (asynchronous — FR-005)."""


# --- Registry ---------------------------------------------------------------

_REGISTRY: dict[str, type[BaseHandler]] = {}


def register(handler_cls: type[BaseHandler]) -> type[BaseHandler]:
    """Class decorator to register a handler implementation by its handler_key."""
    key = handler_cls.handler_key
    if not key:
        raise ValueError(f"{handler_cls.__name__} must define a non-empty handler_key")
    if key in _REGISTRY and _REGISTRY[key] is not handler_cls:
        raise ValueError(f"duplicate handler registration for key {key!r}")
    _REGISTRY[key] = handler_cls
    return handler_cls


def build_registry(
    enabled_handler_keys: list[str],
    client_factories: Mapping[str, ClientFactory],
) -> dict[str, BaseHandler]:
    """Instantiate enabled handlers with their per-type client factories.

    Args:
        enabled_handler_keys: Keys from settings (``pwrsched:resourceTypes``).
        client_factories: Map handler_key -> ClientFactory. A handler is only
            built when both registered and supplied a factory.

    Returns:
        Map handler_key -> handler instance, consumable by the engine.
    """
    # Import side-effect: ensure handler modules are loaded so @register runs.
    from . import _load_all_handlers  # local import avoids cycle at module import

    _load_all_handlers()

    registry: dict[str, BaseHandler] = {}
    for key in enabled_handler_keys:
        cls = _REGISTRY.get(key)
        if cls is None:
            logger.warning("pwrsched.handlers: no handler registered for key %r", key)
            continue
        factory = client_factories.get(key)
        if factory is None:
            logger.warning("pwrsched.handlers: no client factory for key %r; skipping", key)
            continue
        registry[key] = cls(factory)
    return registry
