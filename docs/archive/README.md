# Archived Documents

These documents are finished work, kept as a historical record and no longer updated.

## Phase 1 implementation and code review

| Document | What it covered | Final state |
|---|---|---|
| [PHASE1_TASKS.md](PHASE1_TASKS.md) | Task breakdown and progress log for phase 1 (T-001 to T-603) | 22 of 24 tasks done; T-602 and T-603 completed in the demo tenant ([demo verification record](demo-verification/VERIFICATION.md)) |
| [REVIEW_FINDINGS.md](REVIEW_FINDINGS.md) | Three rounds of code review: findings C1–L6 and N1–N7, with evidence, fixes and a status log | 29 of 29 closed at code level; the 8 live checks passed in the demo tenant except C3 (no SQL MI) — see the [demo verification record](demo-verification/VERIFICATION.md#0-status-tracker) |

## About the IDs

Task IDs (`T-xxx`) and finding IDs (`C1`, `H3`, `N1`, …) are **kept, not removed**:

- Code comments, tests and commit messages refer to them (for example `# N1:` in `src/engine/discovery.py`). The archived files are where those references resolve.
- The [demo verification record](demo-verification/VERIFICATION.md) uses them to say *why* each live check existed.

Do not reuse these IDs. Prefixes already used: `T-`, `C/H/M/L/N` (phase 1), `V1`–`V5` (live verification), `DM-`, `DR-`, `DP-` (demo build, demo review, deploy fixes), `SC-` (scaling), `CH-` (container handlers), `UC-` (use cases), `D-` (decisions).

## Demo tenant verification (`demo-verification/`)

The reference demo tenant was built, dry-run, taken live on 2026-10-06 and
verified over a full live business day (Phase B, closed 2026-10-07).

| Document | What it covered | Final state |
|---|---|---|
| [demo-verification/VERIFICATION.md](demo-verification/VERIFICATION.md) | Demo verification record: dry run (T-602), go-live (T-603), Phase B, issues V1–V5, full results log | All checks passed except C3 (no SQL MI) and App Gateway (not deployed). Superseded for new tenants by the slim runbook [docs/VERIFICATION.md](../VERIFICATION.md). |
| [demo-verification/DEMO_TENANT_PLAN.md](demo-verification/DEMO_TENANT_PLAN.md) | Demo tenant design, budget and scenarios S1–S18 | Built and verified; demo still running (code in `demo/`) |
| [demo-verification/DEMO_TASKS.md](demo-verification/DEMO_TASKS.md) | Demo build tracker (DM-), demo-scaffold review (DR-), live-deploy fixes (DP-) | All closed |

## Large-tenant scaling (v0.7)

| Document | What it covered | Final state |
|---|---|---|
| [SCALING_TASKS.md](SCALING_TASKS.md) | Task breakdown for SC-01–SC-06 and decision D-09 (single cap) | All done in code (v0.7). Requirements stay in [REQUIREMENTS.md §10.1](../REQUIREMENTS.md); operation in README **Large tenants**; rollout in [VERIFICATION.md](../VERIFICATION.md) |
