# Verification Runbook

| Item | Value |
|---|---|
| Document ID | AZ-PWRSCHED-VERIFY-001 |
| Related | [REQUIREMENTS.md](REQUIREMENTS.md), [DEMO_TENANT_PLAN.md](DEMO_TENANT_PLAN.md), [../README.md](../README.md), [archived implementation docs](archive/README.md) |
| Last updated | 2026-10-05 |
| Scope | How to verify the scheduler — static checks (T-601), live dry-run (T-602), go-live (T-603) |

This runbook is the repeatable procedure for verifying the scheduler and is the
single place to track what remains before go-live. T-601 runs offline (and in
CI); T-602/T-603 require a live Azure tenant.

Implementation and code review are finished; their documents are in
[archive/](archive/README.md). Task IDs (`T-xxx`) and finding IDs (`C1`, `N3`, …)
below refer to those archived documents.

---

## 0. Status tracker

Update the **Status** column as each item completes, and record the evidence in
the [results log](#6-results-log).

To run these checks in a disposable demo tenant first, follow
[DEMO_TENANT_PLAN.md](DEMO_TENANT_PLAN.md); its §7 maps each demo scenario to the
items below.

**Status legend:** ⬜ Not started · 🔴 Open issue (code fix needed) · 🔍 Pending live check · 🟡 In progress · ✅ Done · ⛔ Blocked

### Tasks

| ID | Item | Where | Status |
|---|---|---|---|
| T-601 | Static checks and unit tests | [§1](#1-static-checks--unit-tests-t-601) | ✅ Done (enforced in CI) |
| OI-01 | Real `in_scope_management_group_ids` and `excluded_scope_ids` in `terraform.tfvars` | [§2](#2-prerequisites-for-a-live-deploy-t-602t-603) | ✅ Done for the **demo tenant** (`infra/tenants/demo.tfvars`); each real tenant still needs its own |
| T-602 | Deploy and dry-run validation | [§3](#3-deploy--dry-run-validation-t-602) | 🟡 In progress — deployed to demo tenant 2026-10-05; dry-run checklist §3.3 passing; C3/H2/N4 still to run, then ≥1 business day |
| T-603 | Go-live | [§4](#4-go-live-t-603) | ⬜ Not started (needs T-602 complete, all live checks below, and V1 fixed) |
| V1 | AKS-managed node pool scale sets are not excluded from scheduling | [§6.1](#61-issues-found-during-verification) | 🔍 Fixed in code — live check pending (demo scenario S18; AKS/W12 not yet deployed) |
| V2 | One demo resource logged as `unknown-state-skip` every cycle | [§6.1](#61-issues-found-during-verification) | ✅ Fixed (W6 `vmss-demo-w6`; `vmss` handler now reads per-instance power state) — confirmed live 2026-10-05: 0 `unknown-state-skip` |

### Live checks carried over from the code review

Each of these is fixed in code but can only be confirmed on a deployed app. All
must pass before T-603. Background on each ID is in
[archive/REVIEW_FINDINGS.md](archive/REVIEW_FINDINGS.md).

| ID | Live check | Where | Status |
|---|---|---|---|
| C1 | Resources in prod subscriptions logged as `production-excluded`, never acted on | [§3.3](#33-dry-run-checklist-one-cycle--15-min) | ✅ Pass (demo 2026-10-05: W9 `production-excluded` every cycle) |
| C3 | SQL MI `actualState` never `Unknown` | [§3.4](#34-live-verification-of-review-findings), Query 2 | ⬜ Not tested yet — no SQL MI in scope (W14 not deployed; §3.4 permits "not tested") |
| H1 | Decision records carry all OBS-001 fields | §3.4, Query 1 | ✅ Pass (demo 2026-10-05: 0 decisions with empty required fields) |
| H2 | Cycle-health and cycle-exceptions alerts fire | [§5](#5-alert-verification-obs-003004005) | 🔍 Pending — alert-firing tests (S15) not run yet |
| M4 | Timer fires on schedule; past-due recovery; no storage auth errors | §3.4, Queries 3–5 | 🟡 Partial — timer fires 1/15 min, 0 storage auth errors (Q3/Q4 pass); past-due test (Q5) not run yet |
| N3 | Summary count matches invocation count | §3.4, Queries 3 and 6 | ✅ Pass (demo 2026-10-05: 1 summary = 1 invocation per 15m bin) |
| N4 | Mixed-case RG profile inheritance | §3.4, Query 7 | 🔍 Pending — dedicated `RG-PwrSched-CaseTest` fixture not created (W2 `RG-Demo-MixedCase` exists but isn't the N4 query target) |
| N6 | `dryRun` stored as `true` | §3.4, Query 1 | ✅ Pass (demo 2026-10-05: all decisions `dryRun = true`, lowercase) |

---

## 1. Static checks & unit tests (T-601)

No cloud access required. Run from the repo root.

### 1.1 Python unit tests (NFR-009)

```bash
python -m pip install pytest tzdata     # once
python -m pytest -q
```

**Expected:** all tests pass (currently **136 passed, 7 skipped**). The 7 skipped
are the SDK surface checks, which need `src/requirements.txt` installed and run in
the strict `sdk-surface` CI job (§1.3). With the SDKs installed, all 143 pass. The
suite covers the pure evaluator (timezones, midnight crossing, overrides),
discovery (paging, Resource Graph joins and power state), selection (production
hard-exclusion and its fail-safe, tag precedence, scope exclusion),
ordering/safety, the reconcile orchestrator (dry-run, skips, bounded parallel
state reads), the 7 handlers, the telemetry field contract, observability
flushing, and the App Configuration loader + runtime assembly.

### 1.2 Terraform static checks (IAC-008)

```bash
terraform fmt -check -recursive infra/

cd infra/scheduler
terraform init -backend=false -input=false
terraform validate
```

**Expected:** `fmt -check` exits 0 (no diffs); `validate` prints `Success!`.

> `-backend=false` lets `validate` run without state-backend credentials.

### 1.3 CI

These checks run automatically on every push / PR to `main` via
`.github/workflows/ci.yml` (jobs: **Python unit tests**, **SDK surface
(requirements.txt)**, **Ruff lint**, and **Terraform fmt + validate**). The SDK
surface job installs `src/requirements.txt` and runs `tests/test_sdk_surface.py`
with `PWRSCHED_SDK_SURFACE_STRICT=1`, so a missing SDK method fails CI. CI performs **no deployment** and needs no cloud
credentials.

Run the linter locally the same way CI does (finding L5):

```bash
python -m pip install ruff==0.12.0
ruff check src tests        # config in ruff.toml
```

**Expected:** `All checks passed!`.

---

## 2. Prerequisites for a live deploy (T-602/T-603)

1. **Azure access** to the target tenant's **Management** subscription with the
   roles in the README Prerequisites table (resource creation + role
   definitions/assignments at the in-scope MGs).
2. **OI-01 values** — the real scopes for this tenant:
   - `role_assignable_scope` (parent/intermediate MG),
   - `in_scope_management_group_ids` (the non-production MGs to manage),
   - `excluded_scope_ids` (e.g. the Platform MG).
3. **Tooling**: Terraform ≥ 1.9, Azure CLI ≥ 2.60, Azure Functions Core Tools 4.x,
   Python 3.11 (see README Prerequisites).
4. A **Terraform state backend** (README Step 2) in this tenant.

> The Function App installs `src/requirements.txt` during the remote build, so
> the lazy Azure SDK imports in `runtime.py` / `engine/config.py` resolve at
> runtime. No local Azure SDK install is needed to deploy.

---

## 3. Deploy & dry-run validation (T-602)

Production stays excluded throughout; `dry_run` stays `true` until §4.

### 3.1 Sign in to the target tenant

```bash
az login --tenant <tenant-id>
export ARM_SUBSCRIPTION_ID=<management-subscription-id>
export ARM_TENANT_ID=<tenant-id>
```

### 3.2 Configure and deploy

Single-tenant quick path (see README Steps 3–5):

```bash
cd infra/scheduler
cp backend.hcl.example backend.hcl           # edit
cp terraform.tfvars.example terraform.tfvars  # edit (OI-01 values; dry_run = true)
terraform init -backend-config=backend.hcl
terraform plan -out tfplan
terraform apply tfplan
```

Or, for one of several tenants, use the wrapper:

```bash
./infra/deploy.sh <tenant> plan
./infra/deploy.sh <tenant> apply
```

Then publish the function code:

```bash
cd ../../src   # or: cd src
FUNC_APP=$(terraform -chdir=../infra/scheduler output -raw function_app_name)
func azure functionapp publish "$FUNC_APP" --python
```

**Checkpoint — plan review (R-01 safety):** before `apply`, confirm the plan
creates **no** role assignment at the Tenant Root, intermediate root, or
Platform MG. The only MG assignments must be at `in_scope_management_group_ids`.

**Checkpoint — publish:** the publish log ends with:

```
Functions in func-pwrsched-<suffix>:
    reconcile - [timerTrigger]
```

**Checkpoint — host storage settings (DP-04):** after every `apply` **and** every
code publish, confirm the host uses the identity-based storage connection:

```bash
az functionapp config appsettings list -g "$RG" -n "$FUNC_APP" \
  --query "[?starts_with(name, 'AzureWebJobsStorage')].{name:name, value:value}" -o table
```

Pass: `AzureWebJobsStorage__accountName`, `AzureWebJobsStorage__credential`
(`managedidentity`) and `AzureWebJobsStorage__clientId` are set, and the plain
`AzureWebJobsStorage` is **absent or empty**. If it holds a connection string,
the host will fail with storage 403s: remove it and re-apply, then check §3.4
Query 4.

**Checkpoint — no drift (DP-05):** run `plan` again right after `apply`; it
must show **No changes**. Run it as the same identity that applied (DP-06).

### 3.3 Dry-run checklist (one cycle ≈ 15 min)

Query Application Insights (README Step 6 shows the full KQL):

```bash
APPI=$(terraform -chdir=../infra/scheduler output -raw application_insights_name)
RG=$(terraform -chdir=../infra/scheduler output -raw resource_group_name)
az monitor app-insights query --app "$APPI" --resource-group "$RG" \
  --analytics-query 'traces | where customDimensions["pwrsched.event"] == "pwrsched.decision" | take 50'
```

Verify:

- [ ] a `pwrsched.summary` record appears each cycle (OBS-002);
- [ ] only tagged resources from the in-scope MGs appear;
- [ ] **no Platform MG** resources appear;
- [ ] resources in `environment=prod` subscriptions show `result = production-excluded` and are never acted on (BR-003, US-07);
- [ ] `desiredState` matches the expected local time per profile;
- [ ] `dryRun = true` and the Activity Log shows **no** start/stop by the managed identity.

If anything is wrong, fix config (tags / `terraform.tfvars` / profiles) and
re-apply; the engine is idempotent, so no cleanup is needed.

> **Reading dry-run results.** Dry run never starts or stops anything, so:
>
> - **After the evening stop time, every cycle logs `action=stop`** for each
>   running scheduled resource, all night. That is expected, not an error.
> - **Next morning there are no `start` decisions:** resources were never
>   stopped, so they log "already converged" at 08:00–08:30.
>
> To observe start timing and dependency order in dry run, stop a few
> resources by hand the evening before (for example stop a PostgreSQL server
> and deallocate a VM). The next morning's dry-run cycles then log
> `action=start` for the database at 08:00 and for the VM at 08:30.

### 3.4 Live verification of review findings

Several review findings are fixed in code but can only be proven on a deployed
app (status 🔍 in the [§0 tracker](#0-status-tracker)). Run these checks during
the dry run, then update the tracker and the [results log](#6-results-log).
Let the scheduler run for **at least 3 hours** before the count-based checks.

Set up once:

```bash
APPI=$(terraform -chdir=../infra/scheduler output -raw application_insights_name)
RG=$(terraform -chdir=../infra/scheduler output -raw resource_group_name)
FUNC_APP=$(terraform -chdir=../infra/scheduler output -raw function_app_name)
q() { az monitor app-insights query --app "$APPI" --resource-group "$RG" --analytics-query "$1" -o table; }
```

| Finding | Check | Pass condition |
|---|---|---|
| C1 | Production exclusion on a real prod subscription | Covered by §3.3: `result = production-excluded`, never acted on |
| H1 | Decision records carry every OBS-001 field | Query 1 returns rows with no empty columns (except `error`) |
| N6 | Booleans are lowercase | Query 1 shows `dryRun = true` (not `True`) |
| C3 | SQL MI state is read correctly with the 4.x SDK | Query 2: every `sqlmi` row has `actualState` `Running` or `Stopped`, never `Unknown` |
| M4 | Timer fires on schedule with identity-based host storage | Query 3: about 4 invocations per hour; Query 4 returns no storage auth errors |
| M4 | Past-due recovery (FR-007) | After the stop/start test below, Query 5 shows a past-due run |
| N3 | Telemetry is flushed every cycle | Query 3 and Query 6 counts match for the same window |
| N4 | Mixed-case resource group inheritance | Query 7 shows the test VM with the RG's profile |

**Query 1 — decision fields (H1, N6):**

```bash
q 'traces | where timestamp > ago(1h) | where customDimensions["pwrsched.event"] == "pwrsched.decision"
| project runId = customDimensions["pwrsched.runId"], resourceId = customDimensions["pwrsched.resourceId"],
  type = customDimensions["pwrsched.type"], profile = customDimensions["pwrsched.profile"],
  desiredState = customDimensions["pwrsched.desiredState"], actualState = customDimensions["pwrsched.actualState"],
  action = customDimensions["pwrsched.action"], dryRun = customDimensions["pwrsched.dryRun"],
  result = customDimensions["pwrsched.result"], error = customDimensions["pwrsched.error"] | take 20'
```

**Query 2 — SQL MI state (C3):** needs at least one tagged SQL MI in scope.

```bash
q 'traces | where timestamp > ago(1h) | where customDimensions["pwrsched.event"] == "pwrsched.decision"
| where tostring(customDimensions["pwrsched.type"]) =~ "Microsoft.Sql/managedInstances"
| summarize count() by actualState = tostring(customDimensions["pwrsched.actualState"])'
```

**Query 3 — invocations per hour (M4, N3):**

```bash
q 'requests | where timestamp > ago(3h) | where operation_Name == "reconcile"
| summarize invocations = count() by bin(timestamp, 1h)'
```

**Query 4 — host storage errors (M4):**

```bash
q 'traces | where timestamp > ago(3h) | where severityLevel >= 3
| where message has_any ("AzureWebJobsStorage", "Storage", "lease", "AuthorizationPermissionMismatch")
| project timestamp, message | take 20'
```

**Past-due test (M4):** stop the app for longer than one interval, then start it.

```bash
az functionapp stop -g "$RG" -n "$FUNC_APP"
sleep 1200   # 20 minutes
az functionapp start -g "$RG" -n "$FUNC_APP"
```

**Query 5 — past-due run (M4):** run about 5 minutes after the restart.

```bash
q 'traces | where timestamp > ago(30m) | where message startswith "pwrsched: timer past due" | project timestamp, message'
```

**Query 6 — summaries per hour (N3):** compare with Query 3 for the same hours.

```bash
q 'traces | where timestamp > ago(3h) | where customDimensions["pwrsched.event"] == "pwrsched.summary"
| summarize summaries = count() by bin(timestamp, 1h)'
```

**Mixed-case RG test (N4):** create a resource group with a mixed-case name in
an in-scope, non-production subscription (for example `RG-PwrSched-CaseTest`),
put one small VM with no schedule tags of its own in it, and tag **only the resource group** with
`schedule-profile=weekday-0830-1730`. Delete the resource group after the test.

**Query 7 — RG inheritance (N4):**

```bash
q 'traces | where timestamp > ago(1h) | where customDimensions["pwrsched.event"] == "pwrsched.decision"
| where tostring(customDimensions["pwrsched.resourceId"]) contains "RG-PwrSched-CaseTest"
| project resourceId = customDimensions["pwrsched.resourceId"], profile = customDimensions["pwrsched.profile"],
  result = customDimensions["pwrsched.result"]'
```

Checklist:

- [ ] H1 and N6: Query 1 passes
- [ ] C3: Query 2 passes (or recorded as "not tested: no SQL MI in scope")
- [ ] M4: Query 3 shows about 4 invocations per hour, Query 4 is empty, Query 5 shows a past-due run
- [ ] N3: Query 3 and Query 6 counts match
- [ ] N4: Query 7 shows `profile = weekday-0830-1730`
- [ ] H2: both alert tests in [section 5](#5-alert-verification-obs-003004005) fire
- [ ] §0 tracker and §6 results log updated

---

## 4. Go-live (T-603)

After **≥ 1 full business day** of correct dry-run results:

```bash
cd infra/scheduler
# set dry_run = false in terraform.tfvars
terraform plan -out tfplan      # should change ONLY the App Config key pwrsched:dryRun
terraform apply tfplan
```

**Checkpoint:** the plan's only change is `pwrsched:dryRun` → `false`
(IAC-008 — no unexpected drift).

Watch the first live cycles:

- [ ] `pwrsched.decision` records show `result = submitted` for the expected start/stop actions;
- [ ] the Azure **Activity Log** shows the corresponding start/stop operations under the managed identity (SEC-008);
- [ ] alerts are quiet (no `pwrsched.capReached`, no repeated failures).

### Rollback

- Stop acting immediately: set `dry_run = true` and apply (takes effect next cycle).
- Instant halt: `az functionapp config appsettings set -g "$RG" -n "$FUNC_APP" --settings AzureWebJobs.reconcile.Disabled=true`, then set `scheduler_enabled = false` in tfvars and apply.

---

## 5. Alert verification (OBS-003/004/005)

The alert rules key on telemetry events the engine emits:

| Alert | Event / condition |
|---|---|
| OBS-003 cycle health | absence of `pwrsched.summary` for > 45 min |
| OBS-003 cycle exceptions | an `exceptions` row for operation `reconcile` |
| OBS-004 repeated failures | `pwrsched.decision` with `result == "failed"` for the same `resourceId` across 3 runs |
| OBS-005 cap reached | a `pwrsched.capReached` event |

Field alignment between emitted telemetry and the alert/README KQL is checked by
the unit tests (`tests/test_telemetry.py`) and was verified to have **0 gaps**.
To exercise an alert in a test tenant, temporarily lower `max_actions_per_run`
to force a `pwrsched.capReached` event and confirm the action group fires.

**Finding H2 — prove both OBS-003 alerts fire** (do this during the dry run, in
dry-run mode, and restore afterwards):

1. **Cycle health:** set `scheduler_enabled = false` in tfvars and apply. Wait at
   least 60 minutes (45-minute window plus one evaluation). Confirm the
   `<prefix>-cycle-health` alert fires and the action group notifies. Set
   `scheduler_enabled = true` and apply.
2. **Cycle exceptions:** make one cycle throw by pointing it at an invalid App
   Configuration endpoint:

   ```bash
   az functionapp config appsettings set -g "$RG" -n "$FUNC_APP" \
     --settings APP_CONFIG_ENDPOINT=https://invalid.azconfig.io
   ```

   After the next cycle, confirm the `<prefix>-cycle-exceptions` alert fires.
   Then run `terraform apply` to restore the correct endpoint, and confirm the
   next cycle succeeds.

- [ ] Cycle-health alert fired and notified
- [ ] Cycle-exceptions alert fired and notified
- [ ] Settings restored; `terraform plan` shows no changes

---

## 6. Results log

Record each verification run here: what was checked, the outcome, and where the
evidence is (query output, screenshot, alert notification). If a check fails,
log it as a new issue with a `V` prefix (V1, V2, …), fix it, and re-run the check.

| Date | Item(s) | Result | Evidence / notes | By |
|---|---|---|---|---|
| 2026-10-04 | T-601 | ✅ Pass | Re-run locally at `1eb0498`: 143 passed with pinned SDKs (136 passed, 7 skipped without), strict SDK surface 7 passed, ruff clean. Terraform fmt/validate per the CI job. | Claude |
| 2026-10-04 | V1 | 🔴 Issue opened | Design gap found during review of AKS start/stop behaviour; see §6.1. Not yet reproduced live (planned as demo scenario S18). | Claude |
| 2026-10-04 | V1 | 🔍 Fixed in code | discovery projects RG `managedBy` (`rgManagedBy`) and populates `ResourceRecord.resource_group_managed_by`; selection excludes `vm`/`vmss` with reason `aks-managed-node-pool` (an `aks-managed-*` tag key or RG `managedBy` → `managedClusters`, both case-insensitive) or `managed-resource-group` (other non-empty `managedBy`), before opt-in so it is logged; HR-007 added to REQUIREMENTS §8.2. Tests: 13 new (9 selection + 4 discovery). Suite **149 passed / 7 skipped**, ruff clean. Live criterion remains for demo scenario S18. | Kiro |
| 2026-10-05 | T-602 (deploy) | ✅ Pass | Scheduler deployed to demo tenant via `./infra/deploy.sh demo apply` (mgmt sub `6dc67a7b…`, `rg-pwrsched-southeastasia`). Plan R-01 check passed: custom role assigned **only** at `demo-landingzones` + `demo-sandbox`. Function code published (zip remote build); `reconcile - [timerTrigger]` registered. Outputs: func `func-pwrsched-eorw`, appcs `appcs-pwrsched-eorw`, appi `appi-pwrsched`. Required 4 product/config fixes — see 2026-10-05 fixes below. | Kiro |
| 2026-10-05 | C1 | ✅ Pass | Dry-run cycles 06:30/06:45 UTC: prod VM W9 (`rg-demo-prod`, sub tagged `Environment=Prod`) logged `result=production-excluded` every cycle, never acted on. Also BR-003 case-insensitive tag confirmed (mixed-case `Environment=Prod`). | Kiro |
| 2026-10-05 | H1 | ✅ Pass | §3.4 Query 1: decision records carry all OBS-001 fields; 0 records with empty `runId`/`type`/`profile`/`desiredState`/`actualState`/`result` (only `error`/`action` empty when N/A). | Kiro |
| 2026-10-05 | N6 | ✅ Pass | §3.4 Query 1: all 18 decisions across two cycles show `dryRun = true` (lowercase string), matching README/VERIFICATION expectations. | Kiro |
| 2026-10-05 | M4 | 🟡 Partial pass | §3.4 Query 3: `reconcile` invocations = 1 per 15-min bin (06:30, 06:45). Query 4: 0 host storage auth errors in the last 30 min (after the AzureWebJobsStorage fix below). Past-due test (Query 5) not yet run. | Kiro |
| 2026-10-05 | N3 | ✅ Pass | §3.4 Queries 3 & 6: `pwrsched.summary` count (1 per 15-min bin) matches `reconcile` invocation count for the same bins — telemetry flushed every cycle. | Kiro |
| 2026-10-05 | §3.3 dry-run | ✅ Pass | Decision breakdown over 2 cycles: `already-converged`×12, `schedule-disabled`×2 (W4 opt-out), `unknown-state-skip`×2, `production-excluded`×2 (W9). 0 Platform-MG (`rg-demo-platform`/W11) resources in decisions. `dryRun=true`, no Activity-Log actions. | Kiro |
| 2026-10-05 | C3 | ⬜ Not tested | No SQL MI in scope (W14/`enable_sqlmi` not deployed). §3.4 permits recording as "not tested: no SQL MI in scope" until W14 is deployed in Phase B. | Kiro |
| 2026-10-05 | Product fixes (found during T-602 deploy) | ✅ Fixed | Four issues blocked first deploy, all fixed: (1) `infra/scheduler/providers.tf` — added `storage_use_azuread = true` (provider used shared-key for storage data-plane vs SEC-005 key-disabled → 403; also needed deployer Blob/Queue/Table data roles on state + runtime SAs); (2) `infra/modules/function_app/main.tf` — removed `FUNCTIONS_WORKER_RUNTIME` app setting (Flex Consumption rejects it, BadRequest 51021; runtime set via `runtime_name`); (3) `infra/modules/monitoring/main.tf` — renamed cycle-health measure column `cycles`→`cycleCount` (`cycles` is a reserved KQL keyword → "could not be parsed at ')'"); (4) runtime: platform auto-injected a key-based `AzureWebJobsStorage` connection string (empty key) that overrode the identity-based `AzureWebJobsStorage__*` settings and drained the host with 403s — initially removed via `az`, now fixed in code (DP-04: the module pins `AzureWebJobsStorage = ""` so the re-injection can't override the `__*` settings). Items 1–4 are product-code fixes that affect any tenant and should be reviewed/committed. | Kiro |
| 2026-10-05 | V2 | 🔍 Issue opened | Review of the T-602 results: one in-scope resource reads as `unknown-state-skip` every cycle; see §6.1. | Claude |
| 2026-10-05 | DP-01, DP-04, DP-05 | 🔴 Follow-ups recorded | Deploy-fix follow-ups recorded in `demo/TASKS.md` §8: DP-01 (deployer data roles not granted or documented), DP-04 (needs a code fix and a post-deploy check), DP-05 (duplicate `APPLICATIONINSIGHTS_CONNECTION_STRING` makes every plan show a change, which breaks the §4 go-live checkpoint). | Claude |
| 2026-10-05 | DP-01, DP-04, DP-05 | ✅ Fixed in code | DP-04: `infra/modules/function_app/main.tf` pins `AzureWebJobsStorage = ""` (azurerm #29149) so the key-based re-injection can't override the identity-based `__*` settings (replaces the `az` workaround). DP-05: removed the duplicate `APPLICATIONINSIGHTS_CONNECTION_STRING` from `app_settings` (kept in `site_config`) — fixes the perpetual plan drift so the §4 checkpoint can pass. DP-01 follow-up: the `function_app` module now grants the deployer Blob Data Owner + Queue/Table Data Contributor on the runtime SA (`deployer_object_id` wired from the root; deployment container `depends_on` the deployer blob role); README note + Troubleshooting row updated. Validated: `terraform fmt -check -recursive infra/` exit 0, `terraform validate` **Success!**. Live re-plan confirmation (§4 shows only `pwrsched:dryRun`) still pending a deployed tenant. | Kiro |
| 2026-10-05 | DP-04, DP-05, DP-06 | 🔍 Review recorded | Review of `edf3495`: fixes are correct in code but unverified live. Added the host-storage and no-drift checkpoints to §3.2. New DP-06 (deployer role assignments follow the signed-in identity). Before re-applying, delete or import the manually granted deployer storage roles to avoid `409 RoleAssignmentExists` (see `demo/TASKS.md` §8). | Claude |
| 2026-10-05 | Re-deploy, DP-01, DP-04 | ✅ Pass (live) | Re-applied from a fresh laptop (scheduler state is **remote** in `demosatfstate`; `init -reconfigure` pulled it — the other laptop only held the demo landing-zone/workloads *local* state, not needed here). **No manual deployer roles existed to delete:** the 3 roles on `stpwrschedeorw` belong to the managed identity `id-pwrsched` (Terraform-managed, in state), and the signed-in deployer is a *different* identity than the original with only inherited Owner/UAA — so no `409` trap applied to it. `apply`: **3 added** (deployer Blob/Queue/Table roles for the new deployer, DP-01) **+ 1 changed** (func app `AzureWebJobsStorage`→null, DP-04) **+ 0 destroyed**. **DP-04 host-storage checkpoint PASS:** `__accountName=stpwrschedeorw`, `__credential=managedidentity`, `__clientId` set; bare `AzureWebJobsStorage` empty (no key-based re-injection). | Kiro |
| 2026-10-05 | DP-05, DP-06 | 🟡 Partial / open | **No-drift checkpoint NOT clean:** post-apply `plan` shows `0 add / 1 change / 0 destroy` — a *perpetual, benign* `app_settings.AzureWebJobsStorage → null` diff (azurerm #29149: platform re-injects an empty bare value; Terraform keeps wanting it null). The `hidden-link` App Insights tag diff has settled. This recurring diff means the strict §4 go-live checkpoint ("only change is `pwrsched:dryRun`") **cannot pass as-is** — DP-05 is a known upstream issue, not resolved by the duplicate-conn-string removal alone. DP-06 caused no churn this round (original deployer's roles weren't in remote state). | Kiro |
| 2026-10-05 | M4, N3, H1, N6 | ✅ Pass (live) | §3.4 Queries 1/3/4/6 after re-deploy. Q1: all decision records carry OBS-001 fields, `dryRun="true"` (H1/N6). Q3: `reconcile` ≈ 1 invocation/15 min. **Q4: EMPTY — no host storage auth errors (DP-04 confirmed live)**. Q6: `pwrsched.summary` count = invocation count (N3). | Kiro |
| 2026-10-05 | V2 | ✅ Fixed + confirmed live | Identified via §3.4 Q1 as **W6 `vmss-demo-w6`**. Root cause: `vmss` handler read the scale-set-level instance view, which carries no `PowerState/*` for Uniform VMSS → `unknown`. Fixed `src/handlers/vmss.py` to aggregate per-instance power states (`virtual_machine_scale_set_vms.list`/`get_instance_view`); 8 unit tests + SDK-surface rows added (156 passed/8 skipped, ruff clean). Re-published code; **14:00 UTC cycle shows 0 `unknown-state-skip`** (W6 now `already-converged`, `actualState=Stopped`). Remaining: observe W6 while **running** (Phase B/S1L) for the running→deallocate path. | Kiro |

### 6.1 Issues found during verification

#### V1 — AKS-managed node pool scale sets are not excluded from scheduling

| | |
|---|---|
| **Severity** | High |
| **Status** | 🔍 Fixed at code level (2026-10-04) — live criterion pending demo scenario S18 (then → Closed) |
| **Found** | 2026-10-04, review (before live deployment) |
| **Location** | `src/engine/discovery.py` (`build_kql_query`, `_row_to_record`); `src/engine/selection.py`; `src/engine/models.py` |
| **Related** | REQUIREMENTS HR-002, §8.1 (`aks`, `vmss` handlers), FR-032 |

**Description.** AKS node pools are virtual machine scale sets that AKS creates
in the cluster's node resource group (by default `MC_<rg>_<cluster>_<region>`).
The scheduler is designed to control AKS only through the cluster's own
stop/start operation (`aks` handler). Discovery does not distinguish
AKS-managed scale sets from ordinary ones, so if a node pool scale set resolves
a `schedule-profile` tag, the `vmss` handler will deallocate and start it
directly. AKS does not support managing node pool VMs this way, and it can
leave the cluster in a failed or inconsistent state.

A node pool scale set can resolve a profile without anyone tagging it directly:

- the node resource group is tagged (tag inheritance from the RG, FR-013);
- the subscription carries a `schedule-profile` tag (inheritance from the
  subscription — `sub-demo-sandbox` does this in the demo);
- AKS may copy the cluster's tags onto resources in the node resource group
  (to be confirmed in S18).

**Implementation needed (product code):**

1. **Discovery:** in the resource-group join, also project the resource group's
   `managedBy` (e.g. `rgManagedBy = managedBy`), and populate a new
   `ResourceRecord.resource_group_managed_by` field in `_row_to_record`.
2. **Selection:** before tag resolution, mark a scale set **ineligible** with
   reason `aks-managed-node-pool` when either:
   - any of its own tag keys starts with `aks-managed-` (case-insensitive;
     AKS adds tags such as `aks-managed-poolName`), **or**
   - its resource group's `managedBy` points to a
     `Microsoft.ContainerService/managedClusters` resource (case-insensitive).

   Do not rely on the `MC_` name prefix: the node resource group name can be
   customised.
3. **Recommended broadening:** treat any VM or scale set whose resource group
   has a non-empty `managedBy` as ineligible with reason
   `managed-resource-group`. Such groups are owned by another Azure service
   (for example AKS or Azure Databricks), which manages those VMs itself.
4. **Logging:** these resources must produce a decision record with the skip
   reason (not be silently dropped), so a mis-tagged node resource group is
   visible in the logs.
5. **Requirements:** add a handler requirement to REQUIREMENTS §8.2 (e.g.
   HR-007: "Scale sets and VMs in resource groups managed by another service,
   including AKS node pools, are never started or stopped directly").

**Acceptance criteria.**

- [x] Unit tests: scale set with tag `aks-managed-poolName` → `aks-managed-node-pool`;
  scale set in an RG with `managedBy` = an AKS cluster ID (no AKS tags) →
  `aks-managed-node-pool`; tag key and `managedBy` matched case-insensitively;
  ordinary scale set unaffected. *(tests/test_selection.py: `test_v1_*`)*
- [x] Unit test: VM in an RG managed by a non-AKS service → `managed-resource-group`
  (step 3 adopted). *(`test_v1_vm_in_non_aks_managed_rg_is_managed_resource_group`)*
- [x] KQL test asserts the RG join projects `managedBy`.
  *(tests/test_discovery.py: `test_build_kql_projects_rg_managed_by`)*
- [ ] Live (demo scenario S18): with the AKS node resource group tagged
  `schedule-profile=weekday-0830-1730`, its scale sets are logged with
  `aks-managed-node-pool` and never acted on, while the AKS cluster itself is
  stopped and started by the `aks` handler.

**Interim mitigation until fixed:** never tag AKS node resource groups, and do
not put a `schedule-profile` tag on a subscription that contains AKS clusters.

#### V2 — One demo resource logged as `unknown-state-skip` every cycle

| | |
|---|---|
| **Severity** | High |
| **Status** | ✅ Fixed in code and **confirmed live** (2026-10-05) — demo cycle shows 0 `unknown-state-skip` |
| **Found** | 2026-10-05, demo dry run (T-602) |
| **Location** | `src/handlers/vmss.py` (`get_state`) |
| **Related** | FR-004, FR-033, M1, N7, H4 |

**Description.** The §3.3 breakdown over the first two cycles showed
`already-converged`×12, `schedule-disabled`×2 (W4), `production-excluded`×2 (W9)
and `unknown-state-skip`×2 — 9 resources per cycle, so **exactly one in-scope
resource read as Unknown every cycle**. A resource whose state is Unknown is
never started or stopped, so in live mode it would silently stay running.

**Resource identified:** **W6, `vmss-demo-w6`** (`Microsoft.Compute/virtualMachineScaleSets`,
`rg-demo-vmss`), confirmed via §3.4 Query 1 — the only `unknown-state-skip` row,
`actualState = Unknown` every cycle.

**Root cause (defect).** The `vmss` handler read the **scale-set-level** instance
view (`virtual_machine_scale_sets.get_instance_view`). For a **Uniform**-mode
scale set that view carries **no `PowerState/*` status** — only
`ProvisioningState/succeeded` — so `get_state` fell through to `"unknown"`, which
the engine logs as `unknown-state-skip`. Verified against Azure: the scale-set
instance view returned only `ProvisioningState/succeeded`, while the individual
instance (`instance 0`) reported `PowerState/running`. Power state lives on the
**instances**, not the scale-set resource. (Resource Graph also has no power
state for scale sets — M1/N7 — which is why discovery hits the `get_state`
fallback in the first place.)

**Fix.** `src/handlers/vmss.py` `get_state` now aggregates the per-instance power
states via `virtual_machine_scale_set_vms.list` + `.get_instance_view`:

- any instance `running` → `running` (a running VMSS is stopped);
- no running instance, any transitional (`starting`/`stopping`/`deallocating`) → that state (FR-033 skip & retry);
- all instances off and billed (`stopped`) → `stopped-allocated` → deallocate (H4);
- all `deallocated`, or capacity 0 (no instances) → `deallocated` (converged).

Unit tests added in `tests/test_handlers.py` (`test_vmss_*`, 8 cases incl. the V2
regression) and the SDK-surface matrix (`tests/test_sdk_surface.py`) now asserts
`virtual_machine_scale_set_vms.list` / `.get_instance_view`. Suite: **156 passed,
8 skipped** (the SDK-surface checks run in the strict `sdk-surface` CI job);
ruff clean.

**Acceptance criteria.**

- [x] The resource is identified (W6 `vmss-demo-w6`) and the root cause recorded here.
- [x] After the fix, a full dry-run cycle shows **0** `unknown-state-skip` results for in-scope resources (demo 2026-10-05, 14:00 UTC cycle: `already-converged`×7 incl. W6, `production-excluded`×1, `schedule-disabled`×1 — no unknowns). W6 now reads `actualState=Stopped` (it was manually deallocated), proving the handler reads real instance state.
- [ ] Live check with W6 **running** (not just stopped): confirm `get_state` returns `running` and the engine submits a deallocate at the stop boundary (covered by demo scenario during Phase B / S1L; also exercised by the `running`-instance unit tests).
