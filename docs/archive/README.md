# Archived Documents

These documents covered the implementation and code review of phase 1. Both are finished, so the files are kept here as a historical record and are no longer updated.

| Document | What it covered | Final state |
|---|---|---|
| [PHASE1_TASKS.md](PHASE1_TASKS.md) | Task breakdown and progress log for phase 1 (T-001 to T-603) | 22 of 24 tasks done; T-602 and T-603 continue in [VERIFICATION.md](../VERIFICATION.md#0-status-tracker) |
| [REVIEW_FINDINGS.md](REVIEW_FINDINGS.md) | Three rounds of code review: findings C1–L6 and N1–N7, with evidence, fixes and a status log | 29 of 29 closed at code level; 8 live checks continue in [VERIFICATION.md](../VERIFICATION.md#0-status-tracker) |

## About the IDs

Task IDs (`T-xxx`) and finding IDs (`C1`, `H3`, `N1`, …) are **kept, not removed**:

- Code comments, tests and commit messages refer to them (for example `# N1:` in `src/engine/discovery.py`). The archived files are where those references resolve.
- [VERIFICATION.md](../VERIFICATION.md) still uses them to say *why* each live check exists.

Do not reuse these IDs. New issues found during live verification or later phases should use a new prefix (for example `V1`, `V2`, …) and be recorded in the [results log](../VERIFICATION.md#6-results-log).
