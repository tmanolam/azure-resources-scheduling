# Large-Tenant Scaling — Task Breakdown

| Item | Value |
|---|---|
| Document ID | AZ-PWRSCHED-SCALING-TASKS-001 |
| Related spec | [REQUIREMENTS.md §10.1](REQUIREMENTS.md) (v0.5, SC-01–SC-06), FR-034, NFR-002, NFR-011 |
| Created | 2026-10-06 |
| Status legend | ⬜ Not started · 🟡 In progress · ✅ Done · ⛔ Blocked |

> **Context.** REQUIREMENTS v0.5 adds scaling for large tenants (up to 5,000
> in-scope resources). Currently actions are submitted **sequentially** in a
> **5-minute** timeout, limiting throughput to ~200–300 actions per cycle. A
> 4,000-resource transition would take ~20 cycles (5 hours) to clear the
> default cap. These tasks address that.

> **Prerequisite:** T-602 dry-run validation is nearly complete and go-live
> (T-603) is the next milestone. These scaling changes are **additive** (they
> don't break small tenants with default settings) and should land as their own
> reviewed workstream after T-603 stabilises, or in parallel if the team
> decides to.

---

## Open design decision (gate for SC-01/SC-03/SC-05)

> **D-09 (proposed): single vs. separate action caps.**
>
> SC-03 asks: should the cap remain a single `maxActionsPerRun`, or split into
> `maxStopsPerRun` / `maxStartsPerRun`? Mass stops are the risky direction
> (accidentally shutting down everything); mass starts are less dangerous (worst
> case: resources start too early and run a few extra hours).
>
> **Options:**
> - **A.** Keep single `maxActionsPerRun` (simpler; the cap is a safety brake,
>   not a scheduling mechanism).
> - **B.** Separate caps (finer control; a low `maxStopsPerRun` limits blast
>   radius while a higher `maxStartsPerRun` lets resources start on time).
> - **C.** Single cap + a hard floor (e.g. never stop more than 50% of in-scope
>   in one cycle, regardless of cap).
>
> **Recommendation:** start with **A** (the current model), sized per SC-03's
> peak measurement. Add B/C only if operational experience shows a single cap is
> insufficient. Record the decision in REQUIREMENTS §17.1 as D-09.

---

## Task dependency graph

```
D-09 (decision) ──┐
                   ├──► SC-01 (parallel submission) ──┐
SC-02 (timeout)  ──┤                                  ├──► SC-05 (load test) ──► SC-06 (guidance)
SC-04 (telemetry)──┘                                  │
SC-03 (cap sizing) ────────────────────────────────────┘
```

SC-02 and SC-04 are independent and can start immediately. SC-01 benefits from
D-09 being settled. SC-05 exercises SC-01 + SC-02 + SC-04 together and is the
acceptance gate for NFR-002. SC-06 is docs and depends on the implementation
settling.

---

## Tasks

### SC-01 — Parallel action submission (M)

- **Satisfies:** FR-034, NFR-002, R-09
- **Description:** Refactor `execute_actions` in `src/engine/reconcile.py` to
  submit start/stop operations through a bounded `ThreadPoolExecutor`
  (`max_parallel_actions`, default 10), per order group. All order-1
  submissions must complete before order-2 begins; stops run in reverse order.
  Per-action failures are isolated. HTTP 429 handled by the azure-core retry
  policy (M3). Dry-run: no change (sequential logging is fine; no ARM calls).
- **Where:** `src/engine/reconcile.py` (`execute_actions`), `src/engine/models.py`
  (add `max_parallel_actions` to `ReconcileConfig`), `src/runtime.py`, Terraform
  (`var.max_parallel_actions` → App Config key, or app setting).
- **Existing pattern to follow:** `_prefetch_fallback_states` in `plan_actions`
  (N7 fix) already uses a bounded `ThreadPoolExecutor` for state reads.
- **Depends on:** D-09 (affects whether the cap is applied before or per direction)
- **Tests:**
  - [ ] Concurrency never exceeds the bound (same mock pattern as N7's test).
  - [ ] Order groups are respected: order-1 finishes before order-2 begins.
  - [ ] One failure in a group doesn't stop the others.
  - [ ] Dry-run path is unchanged (no parallel overhead).
- **Status:** ⬜ Not started

### SC-02 — Function time budget (M)

- **Satisfies:** NFR-002
- **Description:** Raise `functionTimeout` in `src/host.json` from `00:05:00` to
  `00:12:00` (below the 15-minute cycle interval). Document in README that the
  timeout must be less than `reconcile_schedule`.
- **Where:** `src/host.json`, `README.md` (Troubleshooting or Configuration).
- **Depends on:** nothing
- **Tests:**
  - [ ] `host.json` parses.
  - [ ] README mentions the timeout < interval rule.
- **Status:** ⬜ Not started
- **Effort:** trivial (one-line + one paragraph)

### SC-03 — Cap design and sizing (S)

- **Satisfies:** FR-031, R-09
- **Description:**
  - (a) Document how to size `maxActionsPerRun`: measure the busiest dry-run
    cycle (peak measurement query in REQUIREMENTS §10.1) and set the cap ≈
    peak × 1.2. Add the query + guidance to README and VERIFICATION.
  - (b) Evaluate and record the D-09 decision (single vs. separate caps).
  - If separate caps are adopted, add `maxStopsPerRun`/`maxStartsPerRun` to
    the ordering module and unit-test the cap alert (OBS-005) for each.
- **Where:** README, VERIFICATION, REQUIREMENTS §17.1, potentially
  `src/engine/ordering.py` + `infra/modules/app_config`.
- **Depends on:** D-09
- **Tests:**
  - [ ] (If separate caps) Unit tests for each cap; OBS-005 alert still fires.
  - [ ] (If single cap) sizing guidance is documented.
- **Status:** ⬜ Not started — **blocked on D-09**

### SC-04 — Telemetry volume (M)

- **Satisfies:** NFR-011, OBS-001, OBS-002, R-10
- **Description:**
  1. Add an App Configuration setting `pwrsched:logConvergedDecisions` (default
     `true`; recommend `false` above ~1,000 in-scope resources).
  2. When `false`, `run_reconcile` / the telemetry emitter skips `emit_decision`
     for `already-converged` results. All other results (start, stop, skipped,
     excluded, failed, production-excluded) are always logged.
  3. Add `converged`, `desiredRunning`, `desiredStopped` counts to the
     `pwrsched.summary` event (OBS-002). The hours-saved query Q-G and the
     workbook must work from summary counts when per-resource converged records
     are absent.
  4. Document an ingestion estimate (e.g. 5,000 resources × 96 cycles/day × ~1
     KB = ~460 MB/day with `true`; ~50 MB/day with `false`) and note the
     optional Log Analytics daily cap.
- **Where:** `src/engine/reconcile.py`, `src/engine/telemetry.py`,
  `src/engine/config.py`, `infra/modules/app_config` (new key),
  `infra/scheduler/variables.tf`, `demo/queries/Q-G*.kql`,
  `infra/workbooks/pwrsched-day2-operations.workbook.json`, README.
- **Depends on:** nothing (can start immediately)
- **Tests:**
  - [ ] `logConvergedDecisions=false`: converged decisions suppressed, all others
    still logged.
  - [ ] `logConvergedDecisions=true` (default): behaviour unchanged.
  - [ ] Summary carries `converged`, `desiredRunning`, `desiredStopped` in both modes.
  - [ ] Q-G returns the same total either way (dry-run comparison in the test).
- **Status:** ⬜ Not started

### SC-05 — Load test (M)

- **Satisfies:** NFR-002
- **Description:** A pytest test (or standalone script) that simulates 5,000
  in-scope resources with a 4,000-resource peak transition:
  - Fake discovery returns 5,000 `ResourceRecord`s across multiple profiles,
    subscriptions, and handler types.
  - Fake `get_state` returns with simulated latency (~300 ms).
  - Fake `start`/`stop` returns with simulated latency (~300 ms) and a
    configurable 429-failure rate.
  - Run through `plan_actions` + `execute_actions` (with `dry_run=false`).
  - Assert: cycle completes within 10 minutes (NFR-002); the cap defers the
    excess; `capReached` is set; no unhandled exceptions; order groups respected.
- **Where:** `tests/test_scaling.py` (or `tests/load/`)
- **Depends on:** SC-01, SC-02, SC-04 (tests the combined effect)
- **Tests:**
  - [ ] NFR-002: 5,000 resources planned + up to `maxActionsPerRun` submitted in
    < 10 minutes with simulated latency.
  - [ ] Cap defers excess; `capReached` set.
  - [ ] 429 retries don't break the cycle.
- **Status:** ⬜ Not started

### SC-06 — Operating guidance for large tenants (S)

- **Satisfies:** R-09, R-10
- **Description:** Add a "Large tenants" section to README with:
  - Stagger profiles by business unit (08:00/08:15/08:30/08:45) to lower the
    peak transitions per cycle.
  - ARM write limits are per subscription; very large single subscriptions
    transition more slowly.
  - Set `logConvergedDecisions = false` for > ~1,000 resources.
  - Review App Insights ingestion after the first week; set a daily cap if
    needed.
  - How to size `maxActionsPerRun` from the peak measurement query.
  - Timeout < interval rule (from SC-02).
- **Where:** README.md
- **Depends on:** SC-01, SC-03, SC-04 (content depends on the implementation)
- **Status:** ⬜ Not started

---

## Progress summary

| Task | Priority | Depends on | Status |
|---|---|---|---|
| D-09 (decision) | — | — | ⬜ |
| SC-01 (parallel submission) | M | D-09 | ⬜ |
| SC-02 (function timeout) | M | — | ⬜ |
| SC-03 (cap sizing) | S | D-09 | ⬜ |
| SC-04 (telemetry volume) | M | — | ⬜ |
| SC-05 (load test) | M | SC-01, SC-02, SC-04 | ⬜ |
| SC-06 (guidance) | S | SC-01, SC-03, SC-04 | ⬜ |

---

## Suggested execution order

1. **D-09** — settle the cap design decision (team discussion, ~15 min).
2. **SC-02** — raise timeout (trivial, no dependencies, unblocks SC-05).
3. **SC-04** — telemetry volume (independent, medium effort, unblocks SC-05/06).
4. **SC-01** — parallel submission (depends on D-09, medium effort).
5. **SC-05** — load test (integrates and validates SC-01/02/04 against NFR-002).
6. **SC-03** — cap sizing guidance (after D-09, light if single-cap).
7. **SC-06** — operating guidance (docs, after everything settles).

SC-02 and SC-04 can start **immediately** in parallel. SC-01 starts once D-09
is decided. SC-05 is the acceptance gate. SC-03/06 are docs that follow.
