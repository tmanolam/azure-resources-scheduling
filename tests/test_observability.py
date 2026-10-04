"""Unit tests for telemetry wiring (observability), covering the N3 flush."""

from __future__ import annotations

import os
import sys

_SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

import observability  # noqa: E402


def test_flush_telemetry_noop_when_not_configured(monkeypatch):
    # N3: when telemetry was never configured, flush is a safe no-op and must
    # not attempt to import or call the OpenTelemetry provider.
    monkeypatch.setattr(observability, "_configured", False)
    observability.flush_telemetry()  # must not raise


def test_flush_telemetry_calls_force_flush_when_configured(monkeypatch):
    # N3: when configured, flush_telemetry calls force_flush on the OTel logger
    # provider so the final batch (incl. pwrsched.summary) is exported.
    calls = []

    class _Provider:
        def force_flush(self, timeout_millis):
            calls.append(timeout_millis)

    fake_logs = type(sys)("opentelemetry._logs")
    fake_logs.get_logger_provider = lambda: _Provider()
    monkeypatch.setitem(sys.modules, "opentelemetry._logs", fake_logs)
    monkeypatch.setattr(observability, "_configured", True)

    observability.flush_telemetry(timeout_millis=1234)
    assert calls == [1234]


def test_flush_telemetry_swallows_errors(monkeypatch):
    # N3: a flush failure must never propagate out of a cycle.
    class _Provider:
        def force_flush(self, timeout_millis):
            raise RuntimeError("export boom")

    fake_logs = type(sys)("opentelemetry._logs")
    fake_logs.get_logger_provider = lambda: _Provider()
    monkeypatch.setitem(sys.modules, "opentelemetry._logs", fake_logs)
    monkeypatch.setattr(observability, "_configured", True)

    observability.flush_telemetry()  # must not raise
