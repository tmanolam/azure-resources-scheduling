"""Azure Functions entrypoint — timer-triggered reconciliation (T-205).

Wires the Phase 2 engine into the timer trigger:

  load config (App Configuration via managed identity)
    -> discover (Resource Graph)
    -> select (tags/scope/prod exclusion)
    -> reconcile (desired vs actual, act on diffs)

An HTTP on-demand trigger is deferred to phase 2 of the product (decision D-05,
FR-022). The timer schedule comes from the ``RECONCILE_SCHEDULE`` app setting
(NCRONTAB, UTC; default every 15 minutes — FR-001). On a missed run the cycle
still runs on recovery (FR-007). Single-cycle concurrency is enforced by the
timer singleton (host.json, NFR-004).

The heavy Azure SDK wiring lives in ``_build_runtime`` and is imported lazily so
the engine package stays unit-testable without the SDK installed.
"""

from __future__ import annotations

import logging
import os
import uuid

import azure.functions as func

app = func.FunctionApp()

_SCHEDULE = os.environ.get("RECONCILE_SCHEDULE", "0 */15 * * * *")

# Default start order per handler key (§8.1), used when schedule-order is unset.
_DEFAULT_ORDER = {
    "postgres-flex": 1, "mysql-flex": 1, "sqlmi": 1, "synapse-pool": 1,
    "aks": 2, "appgw": 2,
    "vm": 3, "vmss": 3,
}


@app.function_name(name="reconcile")
@app.timer_trigger(
    schedule=_SCHEDULE,
    arg_name="timer",
    run_on_startup=False,
    use_monitor=True,
)
def reconcile(timer: func.TimerRequest) -> None:
    """Run one reconciliation cycle."""
    run_id = str(uuid.uuid4())
    if timer.past_due:
        logging.info("pwrsched: timer past due; running recovery cycle (FR-007) run=%s", run_id)

    try:
        _run_cycle(run_id)
    except Exception:  # noqa: BLE001 — log and let the alert on cycle failure fire (OBS-003)
        logging.exception("pwrsched: reconciliation cycle failed run=%s", run_id)
        raise


def _run_cycle(run_id: str) -> None:
    """Build the runtime from App Configuration and run the engine cycle."""
    from datetime import datetime, timezone

    from engine.reconcile import ReconcileConfig, run_reconcile
    from engine.selection import select_resources

    runtime = _build_runtime()

    resources = runtime.discover()
    selections = select_resources(
        resources,
        enabled_handler_keys=runtime.enabled_handler_keys,
        exclude_scopes=runtime.exclude_scopes,
        default_order_by_handler=_DEFAULT_ORDER,
    )

    summary = run_reconcile(
        selections,
        now=datetime.now(timezone.utc),
        run_id=run_id,
        profile_provider=runtime.profile_provider,
        handlers=runtime.handlers,
        config=ReconcileConfig(
            dry_run=runtime.dry_run,
            max_actions_per_run=runtime.max_actions_per_run,
        ),
    )
    logging.info(
        "pwrsched.summary: run=%s evaluated=%d started=%d stopped=%d skipped=%d failed=%d",
        summary.run_id, summary.evaluated, summary.started, summary.stopped,
        summary.skipped, summary.failed,
    )


def _build_runtime():
    """Construct the Azure-backed runtime (config, discovery, handlers).

    Delegates to :func:`runtime.build_runtime`, which loads configuration from
    App Configuration via the user-assigned managed identity, builds the
    Resource Graph query function and the handler registry. Azure SDK imports
    are confined to that module so the engine stays unit-testable.
    """
    from runtime import build_runtime

    endpoint = os.environ.get("APP_CONFIG_ENDPOINT")
    if not endpoint:
        raise RuntimeError("APP_CONFIG_ENDPOINT app setting is not configured")
    return build_runtime(endpoint)
