"""Resource-type handlers for the Azure Resource Power Scheduler.

Each handler implements the common interface (get_state, start, stop) defined in
``base`` (T-301) so new resource types can be added without changing the engine
(HR-005, NFR-007).

Handlers:
- vm, vmss, aks, postgres_flex, mysql_flex, sqlmi  (T-302, Must/Should)
- appgw                                            (T-303, Could)

``_load_all_handlers`` imports the concrete handler modules so their
``@register`` decorators run and populate the registry in ``base``.
"""

from __future__ import annotations

_LOADED = False


def _load_all_handlers() -> None:
    """Import all concrete handler modules so they self-register (idempotent)."""
    global _LOADED
    if _LOADED:
        return
    # Importing each module triggers its @register(...) decorator.
    from . import vm, vmss, aks, postgres_flex, mysql_flex, sqlmi, appgw  # noqa: F401

    _LOADED = True
