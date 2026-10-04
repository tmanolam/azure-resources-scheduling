"""Telemetry wiring: configure Azure Monitor OpenTelemetry once (H1).

The scheduler emits structured records with the standard ``logging`` module
(see :mod:`engine.telemetry`). For those records — and their flat ``pwrsched.*``
attributes — to reach Application Insights' ``traces`` table, the Azure Monitor
OpenTelemetry distribution must be configured once per worker process.

This is kept out of :mod:`engine.telemetry` so the engine stays importable and
unit-testable without the Azure SDK: ``configure_telemetry`` imports the distro
lazily and is a no-op (logged) when the package or connection string is absent,
so local/offline runs still work.

Idempotent: safe to call on every invocation; it only configures once.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger("pwrsched.observability")

_configured = False


def configure_telemetry() -> bool:
    """Configure Azure Monitor OpenTelemetry if available. Returns True if active.

    Uses ``APPLICATIONINSIGHTS_CONNECTION_STRING`` (set by the Functions host
    from the linked Application Insights resource). When the distro or the
    connection string is unavailable, logs a warning and returns False so the
    cycle still runs (telemetry just won't be exported).
    """
    global _configured
    if _configured:
        return True

    conn = os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING")
    if not conn:
        logger.warning(
            "pwrsched.observability: APPLICATIONINSIGHTS_CONNECTION_STRING not set; "
            "telemetry will not be exported to Application Insights"
        )
        return False

    try:
        from azure.monitor.opentelemetry import configure_azure_monitor
    except ImportError:
        logger.warning(
            "pwrsched.observability: azure-monitor-opentelemetry not installed; "
            "telemetry will not be exported"
        )
        return False

    # Capture our own loggers (and children) at INFO. The distro installs a
    # LoggingHandler that exports records — and their flat attributes — to the
    # traces table's customDimensions.
    configure_azure_monitor(
        connection_string=conn,
        logger_name="pwrsched",
    )
    logging.getLogger("pwrsched").setLevel(logging.INFO)
    _configured = True
    logger.info("pwrsched.observability: Azure Monitor OpenTelemetry configured")
    return True


def flush_telemetry(timeout_millis: int = 5000) -> None:
    """Force-export any buffered telemetry before the invocation ends (N3).

    The Azure Monitor OpenTelemetry distro exports log records in background
    batches. On Flex Consumption the worker can be scaled in or frozen soon
    after a cycle returns, dropping the final batch — including the
    ``pwrsched.summary`` record, whose absence would also falsely trip the
    OBS-003 cycle-health alert. Calling ``force_flush`` on the logger provider
    at the end of each invocation drains that batch.

    Guarded so a flush failure (or the SDK being absent in local/offline runs)
    never breaks the cycle. No-op when telemetry was never configured.
    """
    if not _configured:
        return
    try:
        from opentelemetry._logs import get_logger_provider

        provider = get_logger_provider()
        force_flush = getattr(provider, "force_flush", None)
        if callable(force_flush):
            force_flush(timeout_millis)
    except Exception:  # noqa: BLE001 — flushing must never break a cycle
        logger.warning("pwrsched.observability: telemetry force_flush failed", exc_info=True)
