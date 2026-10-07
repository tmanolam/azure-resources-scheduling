# Verification Runbook — New Tenant Rollout

| Item | Value |
|---|---|
| Document ID | AZ-PWRSCHED-VERIFY-002 |
| Related | [REQUIREMENTS.md](REQUIREMENTS.md), [USE_CASES.md](USE_CASES.md), [../README.md](../README.md) (deployment steps), [demo verification record](archive/demo-verification/VERIFICATION.md) |
| Last updated | 2026-10-07 |
| Scope | Repeatable checks to deploy, dry-run and go live in **each** tenant |

This runbook is the short, repeatable procedure for rolling the scheduler out to
a tenant. It captures what the reference demo tenant taught us (checkpoints
DP-04 to DP-06, issues V1–V5, query tooling V4). The full demo evidence —
dry run, go-live, Phase B and the results log — is archived in
[archive/demo-verification/](archive/demo-verification/VERIFICATION.md).

Copy the [tenant tracker](#0-tenant-tracker) and [results log](#9-results-log)
for each tenant (for example into the tenant's change ticket), and work through
sections 1–7 in order.

---

## 0. Tenant tracker

| Step | Item | Where | Status |
|---|---|---|---|
| 1 | Static checks pass on the commit being deployed | [§1](#1-static-checks) | ⬜ |
| 2 | Prerequisites and tenant-specific settings agreed | [§2](#2-prerequisites-and-tenant-settings) | ⬜ |
| 3 | Deployed, with all post-deploy checkpoints passing | [§3](#3-deploy-and-post-deploy-checkpoints) | ⬜ |
| 4 | Dry run for at least one full business day | [§4](#4-dry-run--at-least-one-full-business-day) | ⬜ |
| 5 | Alerts verified | [§5](#5-alerts) | ⬜ |
| 6 | Go-live | [§6](#6-go-live) | ⬜ |
| 7 | First live business day verified | [§7](#7-first-live-business-day) | ⬜ |

**Status legend:** ⬜ Not started · 🟡 In progress · ✅ Done · ⛔ Blocked

---

## 1. Static checks

Run on the exact commit you will deploy (CI runs the same):

```bash
python -m pip install -r src/requirements.txt pytest tzdata ruff==0.12.0
python -m pytest -q                       # all tests pass, incl. the role/SDK consistency check
PWRSCHED_SDK_SURFACE_STRICT=1 python -m pytest -q tests/test_sdk_surface.py
ruff check src tests
terraform fmt -check -recursive infra/
(cd infra/scheduler && terraform init -backend=false -input=false && terraform validate)
```

`tests/test_rbac_consistency.py` fails if a handler calls an Azure operation that
the custom role does not grant (lesson from V5). Do not deploy if it fails.

---

## 2. Prerequisites and tenant settings

Agree these with the tenant owner **before** the first deploy:

| Setting | Guidance |
|---|---|
| `in_scope_management_group_ids` | The **non-production** management group(s) only. Do **not** include the production group: the custom role then grants nothing on production, as well as the tag rule (UC-13). |
| `excluded_scope_ids` | The Platform management group, plus any nested groups, subscriptions or resource groups to keep out. |
| `role_assignable_scope` | The intermediate (organisation) management group. |
| `operator_object_id` | An Entra **operators group**, set before the first deploy. Changing it later replaces the deployer role assignments once (DP-06). |
| Production tag | Confirm production subscriptions carry `environment=prod` (exact value, any letter case) and that Azure Policy enforces it (A-08). |
| `enabled_resource_types` | Only the types present and approved. |
| `log_analytics_workspace_id` | Prefer the central workspace (longer retention than the 30-day default). |
| Large estate? | If more than ~1,000 in-scope resources or ~200 transitions per cycle are expected, read README **Large tenants** first; plan `max_parallel_actions` and `log_converged_decisions = false`, and size `max_actions_per_run` from the dry-run peak (§4). |

Workload-owner guidance to share: tag at resource-group level where possible
(UC-05); tag the **AKS cluster**, never its node resource group (UC-15); for
**Flexible** scale sets, tag the member VMs or their resource group, not the
scale set (HR-008).

Tooling: Terraform ≥ 1.9, Azure CLI ≥ 2.60, Python 3.11; a Terraform state
backend in the tenant (README Step 2).

---

## 3. Deploy and post-deploy checkpoints

Deploy with `dry_run = true` (README Steps 3–5), e.g.
`./infra/deploy.sh <tenant> plan` then `apply`, then publish the code.

| Checkpoint | When | Pass condition |
|---|---|---|
| **R-01 plan review** | Before the first `apply` | The plan creates custom-role assignments **only** at `in_scope_management_group_ids` — none at Tenant Root, the intermediate root or Platform. |
| **Publish** | After code publish | `reconcile - [timerTrigger]` is listed. |
| **Host storage (DP-04)** | After **every** `apply` and code publish | `AzureWebJobsStorage__accountName`, `__credential` (`managedidentity`) and `__clientId` are set; the plain `AzureWebJobsStorage` is absent or empty (command below). |
| **No drift (DP-05)** | Right after every `apply` | A second `plan`, run by the same identity (DP-06), shows **No changes**. |
| **First cycles** | 15–30 min after deploy | Query 1 shows decisions; Query 4 shows no storage errors. |

```bash
az functionapp config appsettings list -g "$RG" -n "$FUNC_APP" \
  --query "[?starts_with(name, 'AzureWebJobsStorage')].{name:name, value:value}" -o table
```

---

## 4. Dry run — at least one full business day

Cover both the morning start window and the evening stop window.

- [ ] One `pwrsched.summary` per cycle (Query 6 matches Query 3).
- [ ] Only tagged resources from in-scope groups appear; **no Platform** resources.
- [ ] Production subscriptions: every resource `production-excluded` (Query 1).
- [ ] `desiredState` flips at the expected local times per profile (databases 30 min and AKS / App Gateway 15 min before VMs).
- [ ] No `unknown-state-skip` or `state-read-failed` for in-scope resources (Query 8). If any appear, stop and investigate before go-live (V2, V5 were found this way).
- [ ] `dryRun=true` on every decision, and the Activity Log shows **no** start/stop by the managed identity.
- [ ] **Peak measured** (Query 9): set `max_actions_per_run` ≈ peak × 1.2 (D-09, SC-03).

> **Reading dry-run results.** Nothing is actually stopped, so after the evening
> stop time every cycle logs `action=stop` all night, and the next morning shows
> no `start` decisions. To see start timing and order in dry run, stop a few
> resources by hand the evening before.

---

## 5. Alerts

The demo proved all four alert rules work (H2, S14). In a new tenant, confirm the
**action group recipients** receive a test notification. Optionally repeat the
cycle-exceptions test during the dry run:

```bash
az functionapp config appsettings set -g "$RG" -n "$FUNC_APP" \
  --settings APP_CONFIG_ENDPOINT=https://invalid.azconfig.io
# after the next cycle: the <prefix>-cycle-exceptions alert fires; then restore:
./infra/deploy.sh <tenant> apply
```

---

## 6. Go-live

1. Set `dry_run = false` in the tenant's tfvars.
2. `plan`: the **only** change must be the App Configuration key `pwrsched:dryRun`
   (`"true"` → `"false"`). Anything else: stop and resolve first.
3. `apply`, then watch the next cycles:
   - [ ] decisions show `dryRun=false` and `result=submitted` for expected actions;
   - [ ] Activity Log shows the operations with the scheduler's managed identity as caller;
   - [ ] `failed=0`, no `capReached`, alerts quiet.

**Rollback:** set `dry_run = true` and apply (next cycle). Instant halt:
`az functionapp config appsettings set -g "$RG" -n "$FUNC_APP" --settings AzureWebJobs.reconcile.Disabled=true`.

---

## 7. First live business day

- [ ] **Morning:** starts submitted in order — databases, then AKS / App Gateway, then VMs and scale sets — each with the managed identity in the Activity Log; resources running; following cycles `already-converged`.
- [ ] **Evening:** stops submitted VMs → AKS → databases; resources stopped / deallocated; following cycles `already-converged`.
- [ ] Day-2 workbooks imported (`infra/workbooks/`); the summary workbook shows the day's starts, stops and cycle duration.
- [ ] Workload owners told how to use overrides and opt-out (README **Ad-hoc start or stop**, **Opt out temporarily**).

When the day passes, mark the tenant **live** in its change record.

---

## 8. Queries (command line)

Application Insights is **workspace-based**, so command-line queries use the Log
Analytics workspace tables (`AppTraces`, `AppRequests`, `Properties[...]`,
`TimeGenerated`). The portal, workbooks and alerts use the Application Insights
schema (`traces`, `customDimensions`) — both are correct; do not change the
alerts (V4).

```bash
WS=$(az monitor log-analytics workspace show -g "$RG" --workspace-name <workspace> --query customerId -o tsv)
q() { az monitor log-analytics query --workspace "$WS" --analytics-query "$1" -o table; }
```

**Query 1 — recent decisions**

```bash
q 'AppTraces | where TimeGenerated > ago(1h) | where Properties["pwrsched.event"] == "pwrsched.decision"
| project TimeGenerated, resourceId = Properties["pwrsched.resourceId"], profile = Properties["pwrsched.profile"],
  desired = Properties["pwrsched.desiredState"], actual = Properties["pwrsched.actualState"],
  action = Properties["pwrsched.action"], dryRun = Properties["pwrsched.dryRun"],
  result = Properties["pwrsched.result"], error = Properties["pwrsched.error"] | take 50'
```

**Query 3 — invocations per hour**

```bash
q 'AppRequests | where TimeGenerated > ago(3h) | where OperationName == "reconcile"
| summarize invocations = count() by bin(TimeGenerated, 1h)'
```

**Query 4 — host storage errors**

```bash
q 'AppTraces | where TimeGenerated > ago(3h) | where SeverityLevel >= 3
| where Message has_any ("AzureWebJobsStorage", "Storage", "lease", "AuthorizationPermissionMismatch")
| project TimeGenerated, Message | take 20'
```

**Query 6 — summaries per hour**

```bash
q 'AppTraces | where TimeGenerated > ago(3h) | where Properties["pwrsched.event"] == "pwrsched.summary"
| summarize summaries = count() by bin(TimeGenerated, 1h)'
```

**Query 8 — unreadable states**

```bash
q 'AppTraces | where TimeGenerated > ago(1h) | where Properties["pwrsched.event"] == "pwrsched.decision"
| where tostring(Properties["pwrsched.result"]) in ("unknown-state-skip", "state-read-failed")
| project TimeGenerated, resourceId = Properties["pwrsched.resourceId"], type = Properties["pwrsched.type"],
  result = Properties["pwrsched.result"], error = Properties["pwrsched.error"]'
```

**Query 9 — peak actions per cycle (cap sizing)**

```bash
q 'AppTraces | where Properties["pwrsched.event"] == "pwrsched.decision"
| where tostring(Properties["pwrsched.action"]) in ("start", "stop")
| summarize actions = count() by runId = tostring(Properties["pwrsched.runId"]), bin(TimeGenerated, 15m)
| top 5 by actions desc'
```

---

## 9. Results log

| Date | Tenant | Step | Result | Evidence / notes | By |
|---|---|---|---|---|---|
| | | | | | |

The reference results for the demo tenant are in
[archive/demo-verification/VERIFICATION.md §6](archive/demo-verification/VERIFICATION.md#6-results-log).

---

## Change history

| Date | Change |
|---|---|
| 2026-10-07 | New slim per-tenant runbook (AZ-PWRSCHED-VERIFY-002). The demo verification record (AZ-PWRSCHED-VERIFY-001) moved to `docs/archive/demo-verification/`. |
