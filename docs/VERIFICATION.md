# Verification Runbook

| Item | Value |
|---|---|
| Document ID | AZ-PWRSCHED-VERIFY-001 |
| Related | [REQUIREMENTS.md](REQUIREMENTS.md), [DEMO_TENANT_PLAN.md](DEMO_TENANT_PLAN.md), [../README.md](../README.md), [archived implementation docs](archive/README.md) |
| Last updated | 2026-10-07 |
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
| T-602 | Deploy and dry-run validation | [§3](#3-deploy--dry-run-validation-t-602) | ✅ Dry-run validation complete (demo tenant) — **signed off by review 2026-10-06**. **Confirmed:** §3.3 checklist, S1/S12 morning start window **and the 17:30 stop window (2026-10-06)** = one full business-day dry-run, H1, N3, N4, N6, C1/N5, S3, S9, M4 (incl. past-due), H2 (both alerts fired live). C3 recorded as not tested (no SQL MI). **Caveat:** reverse-order *stop submission* (S12) is only observable live, carried to T-603/Phase B. |
| T-603 | Go-live | [§4](#4-go-live-t-603) | ✅ Done (2026-10-06) — flipped `dry_run=false`; go-live plan showed only `pwrsched:dryRun "true"→"false"` (0 add / 1 change / 0 destroy, strict §4 checkpoint met). First live cycle 14:15:04 UTC: AKS cluster `aks-demo-w12` `action=stop, result=submitted`, confirmed at control plane (`powerState=Stopped`, Activity Log stop by the managed identity, SEC-008); all other in-scope resources `already-converged`; exclusions held; `failed=0`, no `capReached`. V1/S18 closed, DP-05/DP-06 clean. C3 (SQL MI) not tested — out of scope. |
| PB | Phase B — first live business days | [§4.1](#41-phase-b--live-checks-after-go-live) | 🟡 In progress — **first live morning (2026-10-07) fully confirmed** (all §4.1 morning boxes ticked: 08:00 DBs → 08:15 AKS → 08:30 VMs/VMSS → 09:00 sandbox, Activity-Log caller = managed identity, AKS Running 01:19:38 UTC, following cycles `already-converged`); **S5, S10, S11a, S14** and **V3 Flexible-VMSS** verified live. Remaining: the real **17:30 stop window** (S12 reverse-order stop + V2 running→deallocate) and evening-only **S4 / S5b / S11b** |
| V1 | AKS-managed node pool scale sets are not excluded from scheduling | [§6.1](#61-issues-found-during-verification) | ✅ Closed — fixed in code and **verified live** (demo S18, 2026-10-06): node-pool scale set `aks-system-33558043-vmss` logged `aks-managed-node-pool` / `action=none` across two cycles while the cluster was scheduled by the `aks` handler |
| V2 | One demo resource logged as `unknown-state-skip` every cycle | [§6.1](#61-issues-found-during-verification) | ✅ Fixed (W6 `vmss-demo-w6`; `vmss` handler now reads per-instance power state) — confirmed live 2026-10-05: 0 `unknown-state-skip` |
| V3 | `vmss` handler can't read Flexible-mode scale sets | [§6.1](#61-issues-found-during-verification) | ✅ Fixed **and confirmed live** (2026-10-07): a throwaway 1-instance Flexible VMSS `vmss-demo-v3flex` logged `action=none`/`actual=Unknown`/`result=skipped:vmss-flexible-unsupported` across 6 cycles (not `state-read-failed`), then deleted. Uniform: single `list(expand=instanceView)`; Flexible: `HandlerSkip("vmss-flexible-unsupported")`, HR-008; skip-prefix `skipped:` (`4fafb3f`) |
| V4 | `az monitor app-insights query` returns no rows (workspace-based App Insights) | [§6.2](#62-tooling-notes-found-during-verification) | ✅ Fixed (2026-10-07) — CLI tooling (README Step 6, §3.3/§3.4, `collect-evidence.sh`) switched to `az monitor log-analytics query` on the workspace (`AppTraces`/`Properties`/`TimeGenerated`); alerts, workbook and portal queries unchanged |
| V5 | Custom role missing `virtualMachineScaleSets/virtualMachines/read`; W6 VMSS re-submitted `start` every cycle | [§6.1](#61-issues-found-during-verification) | ✅ Fixed + confirmed live (2026-10-07): RBAC read action added + handler capacity-aware; W6 `actualState=Running`, `action=none` |

### Live checks carried over from the code review

Each of these is fixed in code but can only be confirmed on a deployed app. All
must pass before T-603. Background on each ID is in
[archive/REVIEW_FINDINGS.md](archive/REVIEW_FINDINGS.md).

| ID | Live check | Where | Status |
|---|---|---|---|
| C1 | Resources in prod subscriptions logged as `production-excluded`, never acted on | [§3.3](#33-dry-run-checklist-one-cycle--15-min) | ✅ Pass (demo 2026-10-05: W9 `production-excluded` every cycle) |
| C3 | SQL MI `actualState` never `Unknown` | [§3.4](#34-live-verification-of-review-findings), Query 2 | ⬜ Not tested yet — no SQL MI in scope (W14 not deployed; §3.4 permits "not tested") |
| H1 | Decision records carry all OBS-001 fields | §3.4, Query 1 | ✅ Pass (demo 2026-10-05: 0 decisions with empty required fields) |
| H2 | Cycle-health and cycle-exceptions alerts fire | [§5](#5-alert-verification-obs-003004005) | ✅ Pass (demo 2026-10-06: cycle-exceptions Fired 06:32:54 UTC, cycle-health Fired 08:45:10 UTC; confirmed by review 2026-10-06) |
| M4 | Timer fires on schedule; past-due recovery; no storage auth errors | §3.4, Queries 3–5 | ✅ Pass (demo 2026-10-06: timer 1/15 min, 0 storage auth errors; past-due test — app down 05:00–05:20 UTC, `pwrsched: timer past due` recovery at 05:20:57, cadence resumed 05:30; confirmed by review 2026-10-06) |
| N3 | Summary count matches invocation count | §3.4, Queries 3 and 6 | ✅ Pass (demo 2026-10-05: 1 summary = 1 invocation per 15m bin) |
| N4 | Mixed-case RG profile inheritance | §3.4, Query 7 | ✅ Pass (demo 2026-10-06: `vm-demo-w2` in `RG-Demo-MixedCase`, no own tags, resolved `profile=weekday-0830-1730` by RG inheritance; confirmed by review 2026-10-06) |
| N6 | `dryRun` stored as `true` | §3.4, Query 1 | ✅ Pass (demo 2026-10-05: all decisions `dryRun = true`, lowercase) |

---

## 1. Static checks & unit tests (T-601)

No cloud access required. Run from the repo root.

### 1.1 Python unit tests (NFR-009)

```bash
python -m pip install pytest tzdata     # once
python -m pytest -q
```

**Expected:** all tests pass (currently **172 passed, 8 skipped**). The 8 skipped
are the SDK surface checks, which need `src/requirements.txt` installed and run in
the strict `sdk-surface` CI job (§1.3). With the SDKs installed, all 180 pass. The
suite covers the pure evaluator (timezones, midnight crossing, overrides),
discovery (paging, Resource Graph joins and power state), selection (production
hard-exclusion and its fail-safe, tag precedence, scope exclusion),
ordering/safety, the reconcile orchestrator (dry-run, skips, bounded parallel
state reads), the 7 handlers, the telemetry field contract, observability
flushing, the App Configuration loader + runtime assembly, and the role/SDK
consistency check (`tests/test_rbac_consistency.py` — every ARM operation a
handler calls must be granted by the custom role; lesson from V5).

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

Query the backing Log Analytics workspace (README Step 6 explains why the CLI
uses the workspace tables, not `az monitor app-insights query`):

```bash
RG=$(terraform -chdir=../infra/scheduler output -raw resource_group_name)
WS=$(az monitor log-analytics workspace show \
       -g "$RG" --workspace-name log-pwrsched --query customerId -o tsv)
az monitor log-analytics query --workspace "$WS" \
  --analytics-query 'AppTraces | where Properties["pwrsched.event"] == "pwrsched.decision" | take 50'
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

Set up once. The scheduler's Application Insights is **workspace-based**, so the
CLI queries the Log Analytics workspace tables — `AppTraces` / `AppRequests` /
`AppExceptions`, custom dimensions under `Properties[...]`, timestamp
`TimeGenerated`, request name `OperationName` — not the classic `traces` /
`customDimensions` / `timestamp` that `az monitor app-insights query` reads
against a workspace-based resource (it returns no rows). The alerts and workbook
stay on the classic schema in the App Insights scope (see §6.2 / V4).

```bash
RG=$(terraform -chdir=../infra/scheduler output -raw resource_group_name)
FUNC_APP=$(terraform -chdir=../infra/scheduler output -raw function_app_name)
WS=$(az monitor log-analytics workspace show \
       -g "$RG" --workspace-name log-pwrsched --query customerId -o tsv)
q() { az monitor log-analytics query --workspace "$WS" --analytics-query "$1" -o table; }
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
q 'AppTraces | where TimeGenerated > ago(1h) | where Properties["pwrsched.event"] == "pwrsched.decision"
| project runId = Properties["pwrsched.runId"], resourceId = Properties["pwrsched.resourceId"],
  type = Properties["pwrsched.type"], profile = Properties["pwrsched.profile"],
  desiredState = Properties["pwrsched.desiredState"], actualState = Properties["pwrsched.actualState"],
  action = Properties["pwrsched.action"], dryRun = Properties["pwrsched.dryRun"],
  result = Properties["pwrsched.result"], error = Properties["pwrsched.error"] | take 20'
```

**Query 2 — SQL MI state (C3):** needs at least one tagged SQL MI in scope.

```bash
q 'AppTraces | where TimeGenerated > ago(1h) | where Properties["pwrsched.event"] == "pwrsched.decision"
| where tostring(Properties["pwrsched.type"]) =~ "Microsoft.Sql/managedInstances"
| summarize count() by actualState = tostring(Properties["pwrsched.actualState"])'
```

**Query 3 — invocations per hour (M4, N3):**

```bash
q 'AppRequests | where TimeGenerated > ago(3h) | where OperationName == "reconcile"
| summarize invocations = count() by bin(TimeGenerated, 1h)'
```

**Query 4 — host storage errors (M4):**

```bash
q 'AppTraces | where TimeGenerated > ago(3h) | where SeverityLevel >= 3
| where Message has_any ("AzureWebJobsStorage", "Storage", "lease", "AuthorizationPermissionMismatch")
| project TimeGenerated, Message | take 20'
```

**Past-due test (M4):** stop the app for longer than one interval, then start it.

```bash
az functionapp stop -g "$RG" -n "$FUNC_APP"
sleep 1200   # 20 minutes
az functionapp start -g "$RG" -n "$FUNC_APP"
```

**Query 5 — past-due run (M4):** run about 5 minutes after the restart.

```bash
q 'AppTraces | where TimeGenerated > ago(30m) | where Message startswith "pwrsched: timer past due" | project TimeGenerated, Message'
```

**Query 6 — summaries per hour (N3):** compare with Query 3 for the same hours.

```bash
q 'AppTraces | where TimeGenerated > ago(3h) | where Properties["pwrsched.event"] == "pwrsched.summary"
| summarize summaries = count() by bin(TimeGenerated, 1h)'
```

**Mixed-case RG test (N4):** in the demo tenant, W2's resource group
`RG-Demo-MixedCase` already meets these conditions, so run Query 7 with that name
instead of creating a new fixture. Otherwise, create a resource group with a mixed-case name in
an in-scope, non-production subscription (for example `RG-PwrSched-CaseTest`),
put one small VM with no schedule tags of its own in it, and tag **only the resource group** with
`schedule-profile=weekday-0830-1730`. Delete the resource group after the test.

**Query 7 — RG inheritance (N4):**

```bash
q 'AppTraces | where TimeGenerated > ago(1h) | where Properties["pwrsched.event"] == "pwrsched.decision"
| where tostring(Properties["pwrsched.resourceId"]) contains "RG-PwrSched-CaseTest"
| project resourceId = Properties["pwrsched.resourceId"], profile = Properties["pwrsched.profile"],
  result = Properties["pwrsched.result"]'
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

### 4.1 Phase B — live checks after go-live

Go-live (2026-10-06, 21:15 Bangkok) happened outside working hours, so the only
live action so far is one stop (AKS W12). These checks prove the scheduler on
real resources over the first live business days. Record each in the
[results log](#6-results-log) with `dryRun=false` evidence (decision records,
Activity Log entries, and the resources' actual state in Azure).

**First live morning (Wed 2026-10-07, Bangkok):**

- [x] **08:00** — W7 (`psql-demo-w7`) and W8 (`mysql-demo-w8`): `action=start, result=submitted, dryRun=false` at 01:00:05 UTC; Activity Log `DBfor{PostgreSQL,MySQL}/flexibleServers/start/action` Succeeded 01:02:05–07 UTC.
- [x] **08:15** — W12 (`aks-demo-w12`): `action=start, result=submitted` at 01:15:06 UTC; `managedClusters/start/action` Accepted 01:15:06, **Succeeded (powerState=Running) 01:19:38 UTC** (~4.5 min); now `powerState=Running`/`provisioningState=Succeeded`.
- [x] **08:30** — W1, W2, W3, W5 (VMs) and W6 (`vmss-demo-w6`): `action=start, result=submitted` at 01:30:07 UTC; Activity Log 4× `virtualMachines/start/action` + `virtualMachineScaleSets/start/action` all Succeeded by 01:30:17 UTC.
- [x] **09:00** — W10 (`vm-demo-w10`, `sandbox-default`): `action=start, result=submitted` at 02:00:05 UTC.
- [x] Activity Log: the **only** caller for every start/action in 01:00–02:30 UTC is the scheduler managed identity `595bf154-2328-4066-a465-1ed0b9073ea9` (SEC-008).
- [x] Next cycles after the starts: all scheduled resources log `already-converged` (02:30 UTC cycle: W1/W2/W3/W5/W10/W7/W8/W12 all `already-converged`). **Exception:** W6 kept logging `start` until the V5 role fix landed (first `already-converged` at 04:00 UTC) — see V5.
- [x] Exclusions unchanged: W4 `schedule-disabled`, W9 `production-excluded`, AKS node pool `aks-system-33558043-vmss` `aks-managed-node-pool`; no W11 (Platform MG) present.

**First live evening:**

- [ ] **17:30** — all `weekday-0830-1730` resources get `action=stop`, `result=submitted`.
- [ ] **S12 reverse order:** within the 17:30 cycle, stop submissions run VMs/scale set (order 3) → AKS (order 2) → databases (order 1). Check the decision timestamps / Activity Log order.
- [ ] **V2 running path:** W6 goes from `Running` to deallocated (`actualState=Running`, `action=stop`, then `Stopped`/`deallocated` next cycle).
- [ ] **18:00** — W10 (sandbox) `action=stop`, `result=submitted`.
- [ ] Next cycles: `already-converged`; no repeated stops; alerts quiet.

**Phase B scenarios (DEMO_TENANT_PLAN §6, any live day):**

- [ ] S4 — override "work late" (`schedule-override-state=running` past 17:30), stops after the override ends. *(evening — pending the 17:30 boundary)*
- [x] S5 — override "stop early" (2026-10-07): W3 (`rg-demo-override`) tagged `schedule-override-state=stopped` until 16:08 BKK → 08:45 UTC `desired=Stopped, action=stop, submitted` (deallocated); 09:00 `already-converged`; after expiry 09:15 UTC `desired=Running, action=start, submitted` (schedule resumed). Override tags cleared afterwards.
- [ ] S5b — override ad-hoc start in the evening, stops after it ends. *(evening — pending the 17:30 boundary)*
- [x] S10 — drift (2026-10-07): W7 PostgreSQL stopped out of band → 08:30 UTC `actual=Stopped, desired=Running, action=start, submitted`; W7 back to `Ready` within the cycle (self-healed).
- [x] S11a — VM powered off from inside the OS (2026-10-07): `sudo poweroff` on W5 → `PowerState/stopped`; 08:15 UTC cycle read `actual=StoppedAllocated, desired=Running, action=start, submitted` (H4 billed-but-off distinction).
- [ ] S11b — powered off outside hours → deallocated. *(evening — pending the 17:30 boundary)*
- [x] S14 — action cap (2026-10-07): `max_actions_per_run=2` (set via `--auth-mode login`, shared keys disabled) + dev-subscription override to force transitions → 07:45 UTC summary `evaluated=12, started=2, capReached=true`, `pwrsched.capReached` event logged, OBS-005 alert `pwrsched-max-actions-cap` reached `Fired` at 07:46:28 UTC. Restored cap=200 and cleared the override afterwards.

When the morning and evening items have passed on one live day, and the
scenarios above are recorded, mark **PB** ✅ in the §0 tracker.

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
| 2026-10-05 | V2 review, V3, N4, DP-05 | 🔍 Review recorded | Review of `96fb97c` + `8eee22f`: V2 fix correct for Uniform scale sets; 164 tests pass with SDKs, strict SDK surface 8 passed, ruff clean. Opened **V3** (Flexible-mode scale sets unsupported by the per-instance read; see §6.1). N4 can use W2's `RG-Demo-MixedCase` (§3.4 note). DP-05 recommendation recorded in `demo/TASKS.md` §8. Tomorrow's dry run should log `action=start` for W7/W8 at 08:00 and W1/W2/W3/W5/W6 at 08:30 Bangkok (S1/S12; 08:15 slot empty without W12/W13). | Claude |
| 2026-10-05 | V3 | ✅ Fixed in code | `src/handlers/vmss.py` now reads `orchestration_mode` first: **Uniform** → `virtual_machine_scale_set_vms.list(expand="instanceView")` (one call, falls back to per-instance `get_instance_view` if not inlined) then aggregates; **Flexible** → `HandlerSkip("vmss-flexible-unsupported")`. `src/engine/reconcile.py` `_prefetch_fallback_states` now distinguishes a `HandlerSkip` from a read failure, so a Flexible VMSS is logged `skip:vmss-flexible-unsupported` (not `state-read-failed`) and `failed == 0`. Added REQUIREMENTS **HR-008**; 5 new/updated vmss unit tests + 2 reconcile tests + `virtual_machine_scale_sets.get` in the SDK-surface matrix. Suite **161 passed / 8 skipped**, ruff clean. Live check (a real Flexible scale set) carried forward — none in the demo. | Kiro |
| 2026-10-06 | S1, S12, H1, N6, N4, C1, V2 | ✅ Pass (confirmed by review 2026-10-06) | **Morning start window observed** (Tue 2026-10-06, Bangkok), dry-run — these items keep their prior tracker status until the reviewer confirms. **S12 ordering:** 01:00 UTC (08:00 BKK) only W7 `psql-demo-w7` + W8 `mysql-demo-w8` (order 1) log `action=start`; 08:15 slot empty (no W12/W13); 01:30 UTC (08:30 BKK) W1/W2/W3/W5 VMs + W6 `vmss-demo-w6` (order 3) join. All starts `desired=Running, actual=Stopped, dryRun=true` (lowercase → **N6**), all OBS-001 fields populated (**H1**), profile `weekday-0830-1730`. **N4:** W2 (`RG-Demo-MixedCase`, no own tags) inherited the RG profile and logged `start`. **C1/N5:** W9 `production-excluded, action=none` every cycle. Opt-out W4 `schedule-disabled, action=none`. **No Platform-MG (W11/`rg-demo-platform`)** resource in any decision. **V2 running path:** `vmss-demo-w6` read `actual=Stopped` (real per-instance state, not `Unknown`) and logged `action=start`. Steady 9 decisions + 1 summary per 15-min cycle (**N3**). Only the start boundary seen — 17:30 stop side, go-live, and H2/M4/C3/V1/V3 still pending. (CLI query gotcha found while collecting this: see §6.2.) | Kiro |
| 2026-10-06 | S3 | ✅ Pass (confirmed by review 2026-10-06) | **Sandbox subscription-level tag inheritance** (dry-run). After `sub-demo-sandbox` (`a8572700-…`) was placed under the in-scope `demo-sandbox` MG, tagged `environment=sandbox` + `schedule-profile=sandbox-default` (DM-11/12), and W10 `vm-demo-w10` deployed (DM-20, `rg-demo-sandbox`, eastasia), the scheduler discovered it on the **03:45 UTC** cycle. Decision count stepped 9→10 exactly at that cycle (prior cycles 02:30–03:30 had 0 W10). W10 logged `profile=sandbox-default` with **empty own tags** (Resource Graph `tags: {}`), i.e. the profile was **inherited from the subscription tag** — the subscription-level counterpart of N4's RG inheritance. `desired=Running, actual=Running, action=none, result=already-converged` (10:48 BKK is inside the sandbox-default 08:30–18:00 window; W10 deployed running). Exclusions intact in the same cycle (W9 `production-excluded`, W4 `schedule-disabled`, no Platform-MG/W11). Confirms per-profile evaluation across subscriptions (W10 `sandbox-default` vs dev workloads `weekday-0830-1730`). Still pending for sandbox: **S9** (nested-MG exclusion — move the sub into `demo-sandbox-excluded`). | Kiro |
| 2026-10-06 | S9 | ✅ Pass (confirmed by review 2026-10-06) | **Nested-MG exclusion** (dry-run), via `demo/scripts/scenario-move-sandbox-mg.sh`. Moved `sub-demo-sandbox` from the in-scope `demo-sandbox` into the nested **`demo-sandbox-excluded`** (an `excluded_scope_id`), inside the in-scope `demo-sandbox` branch. Resource Graph `managementGroupAncestorsChain` updated to include `demo-sandbox-excluded` within ~1 min. **Clean transition in W10's decisions:** 03:45/04:00 UTC `already-converged` (in scope) → **04:15/04:30 UTC `excluded-scope`, `action=none`** (M2 nested-MG exclusion firing on the ancestry chain). Note the engine still **emits a decision record** for W10 with `result=excluded-scope` (auditable skip), rather than silently dropping it — so a summary count of "W10 present" stays 10; the pass signal is the `result`, not absence. Then `restore` moved the sub back under `demo-sandbox` (MG chain + ARG ancestry confirmed back to `Tenant Root → demo → demo-sandbox`), returning the landing zone to its Terraform-expected placement (no drift). W10 returns to `already-converged` once ARG re-settles. | Kiro |
| 2026-10-06 | M4, S16 | ✅ Pass (confirmed by review 2026-10-06) | **Past-due recovery (FR-007)** test, dry-run. Stopped `func-pwrsched-eorw` 05:00→05:20 UTC (20 min, > the 15-min interval), spanning the 05:15 occurrence. Timeline: summaries at 04:45 & 05:00; **05:15 missed** (app down, no summary); app started 05:20:37; at **05:20:57 UTC** host logged `pwrsched: timer past due; running recovery cycle (FR-007) run=d256b883-…` (Query 5); **recovery summary 05:21:00**; **normal cadence resumed 05:30:03**. Confirms NFR-003 self-heal: missed cycle → immediate run on recovery → regular schedule resumes. **DP-04 across cold-start:** Query 4 (host storage auth errors) **empty** after the restart — the identity-based `AzureWebJobsStorage__*` connection held, no 403s. `az functionapp` commands required explicit `--subscription 6dc67a7b-…` (demo management sub) as the CLI default had shifted. This advances the M4 tracker item from 🟡 partial toward complete (past-due was the outstanding piece). | Kiro |
| 2026-10-06 | N4 | ✅ Pass (confirmed by review 2026-10-06) | **Mixed-case RG inheritance** (Query 7), dry-run. `vm-demo-w2` — whose resource ID preserves the exact casing `resourceGroups/RG-Demo-MixedCase` and which has **no own schedule tags** — resolved `profile=weekday-0830-1730`, inherited from the **RG-level** tag. Confirms the N4 fix (KQL lowercases both sides of the RG join, `rgKey = tolower(resourceGroup)`), so a mixed-case RG name does not break inheritance. Used W2's existing `RG-Demo-MixedCase` rather than a new fixture, per the §3.4 note. | Kiro |
| 2026-10-06 | DP-05 | ✅ Fixed + confirmed live | **Clean plan achieved — strict §4 go-live checkpoint can now pass.** A live `./infra/deploy.sh demo plan` (remote state `demosatfstate`) first showed the `AzureWebJobsStorage` diff was already **gone** (the earlier `ignore_changes` works), but revealed a *residual* `0 add / 1 change / 0 destroy`: Azure injects a `hidden-link: /app-insights-resource-id` **tag** on the Function App (from `site_config.application_insights_connection_string`) that is not in `var.tags`, so Terraform wanted to strip it every plan. **Fix:** added `tags["hidden-link: /app-insights-resource-id"]` to the existing `lifecycle { ignore_changes }` on `azurerm_function_app_flex_consumption.this` (`infra/modules/function_app/main.tf`), alongside the `AzureWebJobsStorage` entry. Re-plan → **"No changes. Your infrastructure matches the configuration."** `terraform fmt -check -recursive infra/` exit 0, `terraform validate` Success. Our own tags (owner/cost-centre/project/managed-by) are still enforced. Note: `ignore_changes` is persisted to state on the next `apply`; the plan already reads clean, so the go-live `dry_run=false` apply will show only the `pwrsched:dryRun` change. Supersedes the 2026-10-05 note that an `AzureWebJobsStorage` diff persisted (now stale). | Kiro |
| 2026-10-06 | Review of morning session | ✅ / 🔴 | Review of `d86946b`, `be3cc45`, `9f000d5` and the 2026-10-06 records. **Confirmed:** S1/S12 (08:00 W7/W8 only; 08:15 empty; 08:30 W1/W2/W3/W5/W6), H1, N3, N6, N4, C1/N5, S3, S9 (logged `excluded-scope` rather than dropped — preferred for audit), M4 incl. past-due (S16), DP-05 (`plan` = No changes), V2 running path. Tests: 169 passed with SDKs, ruff clean. **V3 follow-up opened:** plan-time skips are logged `skip:<reason>` but execution-time skips `skipped:<reason>`, so the workbook "Failed or skipped" panel misses Flexible scale set skips. **V4 decision:** switch CLI tooling to the workspace; keep portal/workbook/alerts on `traces` (alerts are scoped to the App Insights resource, where `traces` works). Next: H2 (S15), today's 17:30 stop window, V1/S18 decision. | Claude |
| 2026-10-06 | H2 (cycle-exceptions) | ✅ Pass (confirmed by review 2026-10-06) | **Cycle-exceptions alert fired live** (dry-run). Broke `APP_CONFIG_ENDPOINT` → `https://invalid.azconfig.io` at 06:20 UTC; the **06:30 cycle threw** two `reconcile` exceptions (`AppExceptions`, `OperationName=reconcile`) and emitted **no summary**. The `pwrsched-cycle-exceptions` scheduled-query alert reached **`monitorCondition=Fired`** at 06:32:54 UTC — proving its `exceptions | where operation_Name == "reconcile"` query resolves against the **workspace-based** App Insights and fires end-to-end. Restored the endpoint at 06:37; scheduler **recovered** with a normal `pwrsched.summary` at 06:45:03. | Kiro |
| 2026-10-06 | H2 (cycle-health) | ✅ Pass (confirmed by review 2026-10-06) | **Cycle-health alert fired live** (dry-run) — completes H2. Stopped `func-pwrsched-eorw` 07:45→08:50 UTC (~65 min; last summary 07:45:02). With no `pwrsched.summary` for the full 45-min window, `pwrsched-cycle-health` reached **`monitorCondition=Fired` (Sev1) at 08:45:10 UTC**. On restart (08:50), the host logged `pwrsched: timer past due` (08:50:25) and a recovery summary (08:50:27), so the scheduler self-healed. **Both OBS-003 alerts now proven end-to-end:** cycle-exceptions (06:32:54) and cycle-health (08:45:10). | Kiro |
| 2026-10-06 | DP-05 | ⚠️ Correction | Earlier same-day entry said the live plan was clean. A fuller `./infra/deploy.sh demo plan` shows the config fix is correct but the `hidden-link` tag diff **still appears until the next `apply`** — `ignore_changes` only takes effect once persisted to state, and the current state predates the fix. All deployer role assignments refresh with no change (so DP-06 refactor adds no churn). Net: the plan will be clean **after** the next apply (e.g. the go-live `dry_run=false` apply), which then shows only `pwrsched:dryRun`. The §4 checkpoint should be evaluated on the post-apply plan, not before. | Kiro |
| 2026-10-06 | DP-06 | ✅ Fixed in code (offline-validated) | **Deployer data-plane roles decoupled from the running identity.** Added `var.operator_object_id` (default `""`) + `local.deployer_object_id = var.operator_object_id != "" ? var.operator_object_id : data.azurerm_client_config.current.object_id` in `infra/scheduler/main.tf`; both the `app_config` and `function_app` module calls now pass `local.deployer_object_id` instead of the raw current-identity object ID. Set it to a stable **operators group** object ID so a different person/CI can run plan/apply without replacing the App Configuration Data Owner + Storage Blob/Queue/Table deployer role assignments (which would churn the plan and revoke the prior deployer's access). Default preserves first-deploy behaviour. `terraform fmt`/`validate` clean; **live plan shows the deployer role assignments refresh with 0 change** (default resolves to the same identity → no churn). The design concern in `demo/TASKS.md` §8 DP-06 is addressed; using a group is now a config choice (`operator_object_id`), not a code change. | Kiro |
| 2026-10-06 | S1 (stop window), S12 | ✅ Pass (dry-run) | **17:30 Bangkok stop window observed**, completing a full business-day dry-run cycle (morning start already recorded earlier today). Queried the **workspace-based** App Insights via Log Analytics (`log-pwrsched`, workspace `17e29095-…`, `AppTraces`/`Properties["pwrsched.*"]`/`TimeGenerated` — per V4; `az monitor app-insights query` returns nothing). **At 10:30:03 UTC (= 17:30 BKK)** the cycle evaluated all 10 in-scope resources and every `weekday-0830-1730` resource's desired state flipped to `Stopped` exactly at the profile boundary: order-1 DBs `psql-demo-w7`/`mysql-demo-w8` and order-3 `vm-demo-w1/w2/w3/w5` + `vmss-demo-w6`. Because it is **dry-run**, those resources were never actually started, so `actual=Stopped` already → each logged `already-converged` (desired now matches actual) — the expected §3.3 dry-run reading; the desired-state recompute to `Stopped` at 17:30 is the evidence. **Exclusions held:** W4 `schedule-disabled`, W9 `production-excluded` (C1/N5), no Platform-MG/W11 present. **Second boundary confirmed:** `vm-demo-w10` (sandbox, `sandbox-default` window to 18:00 BKK) stayed `Running`/`already-converged` at 17:30, then flipped to `desired=Stopped, actual=Running, action=stop` from **11:00 UTC (= 18:00 BKK)** — per-profile boundary evaluation across subscriptions. Summary 10:30:03Z: `evaluated=10, started=0, stopped=0, skipped=10, failed=0`; steady 1 summary/cycle (N3). **Caveat:** true **reverse-order stop submission** (VMs before DBs, `result=submitted`) is not observable in dry-run — all resources were already `Stopped` so no stop operations were sequenced, and the profile stops all orders at 17:30 (only *start* has per-order offsets). That remains a **go-live/Phase-B (S12)** check. | Kiro |
| 2026-10-06 | S18 / V1 | ✅ Pass (dry-run) — V1 closed live | **AKS node-pool protection verified live** (HR-007). Provisioned W12 `aks-demo-w12` (Free tier, node `Standard_B2s_v2` — `Standard_B2s` is `NotAvailableForSubscription` in eastasia; `enable_aks=true`, SQL MI stays out of scope by user decision), node RG `rg-demo-aks-nodes`, `provisioningState=Succeeded`/`powerState=Running`. The node-pool scale set `aks-system-33558043-vmss` carries 16 `aks-managed-*` tags (`aks-managed-poolName=system`, …) and **no** `schedule-profile`, so AKS did not copy the cluster tag. **S18 fixture:** tagged the node RG `rg-demo-aks-nodes` `schedule-profile=weekday-0830-1730` (13:41 UTC) so the scale set became discoverable via RG inheritance; confirmed in ARG. **Result — two consecutive cycles (13:45:02 and 14:00:02 UTC):** the node-pool scale set logged `action=none, result=aks-managed-node-pool` (never read/acted on), while the cluster `aks-demo-w12` was scheduled normally by the `aks` handler (`action=stop`, dry-run, correct post-17:30). This is the V1 fix (`_managed_rg_exclusion_reason`: `aks-managed-*` tag key path) reproducing correctly on real AKS tags. **Fixture removed** afterwards (`az tag update --operation Delete`) — node RG back to AKS-managed tags only. V1 live criterion met → V1 closed. | Kiro |
| 2026-10-06 | T-603 — GO-LIVE | ✅ Done (live) | **Scheduler flipped to live (`dry_run=false`) with AKS in scope.** Set `dry_run=false` in `infra/tenants/demo.tfvars`; `./infra/deploy.sh demo plan` showed **exactly one change** — `pwrsched:dryRun "true"→"false"`, `0 add / 1 change / 0 destroy` (strict §4 / IAC-008 checkpoint met; DP-04/DP-05 `ignore_changes` held, DP-06 no role churn). Applied 14:15 UTC (~21:15 BKK). **First live cycle 14:15:04 UTC:** `dryRun=false` on all decisions; the one real action was **`aks-demo-w12` → `action=stop, result=submitted`** (cluster was Running, past the 17:30 BKK stop boundary). All already-stopped dev resources `already-converged`; **W10 `already-converged`** (user manually stopped it just before go-live); exclusions held live (W4 `schedule-disabled`, W9 `production-excluded`, no Platform-MG/W11). **Control-plane confirmation (SEC-008):** `az aks show` → `powerState=Stopped`; Activity Log `Stop Managed Cluster` (Started 14:15:04.49, Accepted 14:15:04.91) with **caller `595bf154-2328-4066-a465-1ed0b9073ea9` = the scheduler managed-identity principal**. Summary 14:15:04Z: `evaluated=11, started=0, stopped=1, skipped=10, failed=0`; **no `capReached`**, alerts quiet. SQL MI (C3) remains not tested — no SQL MI in scope. | Kiro |
| 2026-10-06 | Review of go-live | ✅ Signed off | Review of `f043eea`…`afe862d` and all docs. **Signed off:** T-602 (full business-day dry run), H2 (both alerts fired live — also confirms the V4 reasoning that alerts work in the App Insights scope), T-603 go-live (only `pwrsched:dryRun` changed; first live cycle stopped AKS, confirmed at the control plane with the scheduler identity in the Activity Log), V1 closed live (S18), V3 `skipped:` prefix fix (summary `skipped` count includes plan-time skips). Tests 169 passed, ruff clean. **Open:** Phase B live checks (§4.1, new tracker row PB), V3 live check (no Flexible scale set), V4 CLI tooling, C3 not tested (SQL MI out of scope). | Claude |
| 2026-10-07 | V5 | ✅ Fixed + confirmed live | First live morning (Phase B): W6 `vmss-demo-w6` logged `actualState=Stopped`/`action=start`/`result=submitted` every cycle from 01:30 UTC (08:30 BKK) despite the instance being `PowerState/running`. Root cause: custom role lacked `Microsoft.Compute/virtualMachineScaleSets/virtualMachines/read`, so ARM authorization-filtered the per-instance list to empty and the handler read the running scale set as `deallocated` (capacity-0 branch). Fix 1: added the read action to `infra/modules/rbac/main.tf` + REQUIREMENTS §11.1 (demo apply `0 add / 1 change / 0 destroy`, role def updated in-place). Fix 2: `src/handlers/vmss.py` now reads `sku.capacity` from the existing `virtual_machine_scale_sets.get` and returns `unknown` (not `deallocated`) when the instance list is empty but capacity > 0, so a future permission gap is a visible skip, not silent churn. Verified: pytest 162 passed/8 skipped, strict SDK-surface 8 passed, ruff clean, `terraform fmt`/`validate` clean. Re-published code; **04:00:03 UTC cycle: W6 `actualState=Running`, `action=none`, `result=already-converged`** — churn ended. | Kiro |
| 2026-10-07 | V4 | ✅ Fixed | Switched the documented **CLI** evidence tooling to the backing Log Analytics workspace (the App Insights is workspace-based, so `az monitor app-insights query` returns no rows). README Step 6, VERIFICATION §3.3 and §3.4 (q() helper + Queries 1–7) now use `az monitor log-analytics query --workspace <customerId>` with `AppTraces`/`AppRequests`/`AppExceptions`, `Properties["pwrsched.*"]`, `TimeGenerated`, `OperationName`. `demo/scripts/collect-evidence.sh` resolves the workspace customerId and translates the saved portal `.kql` files to the workspace schema on the fly (traces→AppTraces, customDimensions→Properties, timestamp→TimeGenerated, etc.). **Left unchanged:** the four alert rules, the day-2 workbook, and the portal `.kql` files (classic `traces`/`customDimensions` in the App Insights scope — proven working by H2 live and the workbook). Added schema notes in README Step 6 and §3.4. `bash -n demo/scripts/collect-evidence.sh` clean. | Kiro |
| 2026-10-07 | V3 (live) | ✅ Pass | Flexible-mode VMSS live check. Created a throwaway 1-instance **Flexible** scale set `vmss-demo-v3flex` (dev, `rg-demo-vmss`, eastasia, `Standard_B2ts_v2`), tagged `schedule-profile=weekday-0830-1730`. Across 6 cycles (05:45–07:00 UTC) it logged `action=none`, `actual=Unknown`, `result=skipped:vmss-flexible-unsupported` — **not** `state-read-failed`, `failed=0`, and the `skipped:` prefix (so the workbook "Failed or skipped" panel and the summary `skipped` count include it). Confirms the V3/HR-008 Flexible path end-to-end. **Deleted** the VMSS afterwards. **Note:** `az vmss create` also auto-created a load balancer (`vmss-demo-v3flexLB`) and NSG (`vmss-demo-v3flexNSG`); `az vmss delete` does **not** remove them, so both were deleted separately (verified `rg-demo-vmss` back to only `vmss-demo-w6`) — baseline restored. When running the V3 check in a real tenant, delete the auto-created LB/NSG too (or create the Flexible VMSS with `--load-balancer ""`). | Kiro |
| 2026-10-07 | S14 (Phase B) | ✅ Pass | Action cap + OBS-005. Set `pwrsched:maxActionsPerRun=2` (via `az appconfig kv set --auth-mode login` — the store has shared keys disabled, SEC-005) and a dev-subscription override to force many transitions. 07:45 UTC cycle: `pwrsched.capReached` event logged; summary `evaluated=12, started=2, capReached=true` (only the cap's worth submitted, rest deferred). OBS-005 alert `pwrsched-max-actions-cap` reached `monitorCondition=Fired` at 07:46:28 UTC. **Restored** cap=200 and cleared the dev override; resources recovered over the next cycles. | Kiro |
| 2026-10-07 | S11a (Phase B) | ✅ Pass | Powered-off (not deallocated) VM, inside hours (H4). `az vm run-command … sudo poweroff` on W5 (`rg-demo-poweroff`) → `PowerState/stopped` (allocated, billed). 08:15 UTC cycle read `actual=StoppedAllocated, desired=Running, action=start, result=submitted` — the handler correctly distinguished an OS-level poweroff from `deallocated` and started it. | Kiro |
| 2026-10-07 | S10 (Phase B) | ✅ Pass | Drift correction. Stopped W7 PostgreSQL (`rg-demo-db`) out of band during business hours → 08:30 UTC cycle `actual=Stopped, desired=Running, action=start, result=submitted`; W7 back to `Ready` within the cycle. Self-heal (NFR-003) confirmed live; also models the 7-day platform auto-restart (HR-003). | Kiro |
| 2026-10-07 | S5 (Phase B) | ✅ Pass | Stop-early override lifecycle. W3 (`rg-demo-override`) tagged `schedule-override-state=stopped`, `schedule-override-until=16:08+07:00`. 08:45 UTC `desired=Stopped, actual=Running, action=stop, submitted` (W3 deallocated); 09:00 `already-converged`; after expiry 09:15 UTC `desired=Running, action=start, submitted` (schedule resumed, W3 starting). Confirms BR-004 override precedence and resumption. Cleared the override tags afterwards. | Kiro |
| 2026-10-07 | V5 review follow-up | ✅ Addressed | Reviewer flagged the V5 role fix as **incomplete**: the vmss handler's per-instance fallback calls `get_instance_view`, which needs `Microsoft.Compute/virtualMachineScaleSets/virtualMachines/instanceView/read` in addition to `.../virtualMachines/read`. Reviewer added that action to `infra/modules/rbac/main.tf` (`29ad8fb`) + REQUIREMENTS §11.1 (`80a303d`, v0.6.2) and a new **`tests/test_rbac_consistency.py`** that statically scans each handler's SDK calls and asserts the custom role grants the matching ARM action (guards against the role/SDK drift that caused V5). I pulled both commits, ran the suite (**172 passed / 8 skipped**; the consistency test's 10 cases pass), and **applied the role change live** to the demo tenant (`./infra/deploy.sh demo apply` → `0 add / 1 change / 0 destroy`; `az role definition list` now shows all three vmss read actions; re-plan "No changes"). | Kiro |
| 2026-10-07 | PB — first live morning | ✅ Pass | **First live start-of-day (01:00–02:00 UTC = 08:00–09:00 BKK), `dryRun=false`.** Decision log `action=start, result=submitted` matched the schedule exactly: **01:00** W7 `psql-demo-w7` + W8 `mysql-demo-w8` (order 1); **01:15** W12 `aks-demo-w12` (order 2); **01:30** W1/W2/W3/W5 VMs + W6 `vmss-demo-w6` (order 3); **02:00** W10 `vm-demo-w10` (`sandbox-default`). **Activity Log (SEC-008):** the only caller for every start/action was the managed identity `595bf154-2328-4066-a465-1ed0b9073ea9` — DB starts Succeeded 01:02:05–07, VM/VMSS Succeeded by 01:30:17; **AKS `managedClusters/start/action` Succeeded (powerState=Running) at 01:19:38 UTC** (~4.5 min after submit; now `powerState=Running`/`Succeeded`). **Following cycles `already-converged`** for all scheduled resources (02:30 cycle: W1/W2/W3/W5/W10/W7/W8/W12). **Exclusions held:** W4 `schedule-disabled`, W9 `production-excluded`, AKS node pool `aks-managed-node-pool`, no W11. **One exception:** W6 kept re-submitting `start` until the V5 role fix (first `already-converged` 04:00 UTC) — tracked under V5. §4.1 morning boxes ticked. | Kiro |

### 6.1 Issues found during verification

#### V1 — AKS-managed node pool scale sets are not excluded from scheduling

| | |
|---|---|
| **Severity** | High |
| **Status** | ✅ Closed — fixed at code level (2026-10-04) and **verified live** (demo scenario S18, 2026-10-06) |
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
- [x] Live (demo scenario S18, 2026-10-06): with the AKS node resource group tagged
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
- [x] Live check with W6 **running**: confirmed 2026-10-07 — after the V5 role fix,
  W6 reads `actualState=Running` live (04:00 UTC cycle, `already-converged`), so
  the handler reads real per-instance running state. The **running→deallocate at
  the stop boundary** is the PB 17:30 item (same as the V2 running path there).

#### V3 — `vmss` handler can't read Flexible-mode scale sets

| | |
|---|---|
| **Severity** | Medium (High for tenants that use Flexible scale sets) |
| **Status** | ✅ Fixed in code (2026-10-05) — **skip-prefix follow-up fixed 2026-10-06** (`4fafb3f`, below); live check pending (no Flexible VMSS in the demo tenant) |
| **Found** | 2026-10-05, review of the V2 fix (`96fb97c`) |
| **Location** | `src/handlers/vmss.py` (`get_state`) |
| **Related** | V2, FR-004, HR-001, NFR-002 |

**Description.** The V2 fix reads power state per instance through
`virtual_machine_scale_set_vms` (`list` + `get_instance_view`). That API works for
**Uniform** orchestration mode (the demo's W6), but Azure does not support it for
**Flexible** mode, which is now the default for new scale sets. For a Flexible
scale set, `get_state` would fail every cycle (`state-read-failed`) and the scale
set would never be started or stopped.

Related points:

- **Double handling:** Flexible members are ordinary VM resources. If they
  inherit a `schedule-profile` (from their resource group or subscription), the
  `vm` handler acts on each member while the `vmss` handler acts on the scale set.
- **API cost (Low):** for Uniform scale sets the fix makes one `list` call plus one
  `get_instance_view` call per instance, every cycle (51 calls for a 50-instance
  scale set). `virtual_machine_scale_set_vms.list(..., expand="instanceView")`
  returns the same data in one call.

**Recommended fix.**

1. Read the scale set's `orchestration_mode` first.
2. **Uniform:** keep the per-instance aggregation, using
   `list(..., expand="instanceView")` instead of one call per instance.
3. **Flexible:** either read member power states another way (for example the
   member VMs from Resource Graph, where `properties.virtualMachineScaleSet.id`
   equals the scale set ID), or raise `HandlerSkip("vmss-flexible-unsupported")`
   so it is logged and not counted as a failure. Document the choice in
   REQUIREMENTS §8.2.
4. Decide how Flexible members are handled by the `vm` handler (schedule the scale
   set **or** its members, not both) and record it as a handler requirement.

**Acceptance criteria.**

- [x] Unit tests: Uniform scale set (running / deallocated / stopped-allocated /
  transitional / capacity 0); Flexible scale set skipped with
  `vmss-flexible-unsupported` (`failed == 0`, logged as `skip:` not
  `state-read-failed`); the single-call `expand="instanceView"` path (one `list`,
  no per-instance `get_instance_view`). *(tests/test_handlers.py `test_vmss_*`,
  tests/test_reconcile.py `test_fallback_handler_skip_*`)*
- [x] SDK surface test covers the new client calls (`virtual_machine_scale_sets.get`,
  `virtual_machine_scale_set_vms.list`/`get_instance_view`).
- [x] Handler requirement recorded (REQUIREMENTS §8.2 **HR-008**): Uniform
  aggregation; Flexible skipped; tag member VMs not the scale set (and not both).
- [ ] If a Flexible scale set is available in the demo tenant: one dry-run cycle
  shows `skip:vmss-flexible-unsupported` for it, and no `state-read-failed`.
  (Not available in the current demo — W6 is Uniform; carry to a tenant that has
  a Flexible scale set.)

**Follow-up (review 2026-10-06) — inconsistent skip prefix.** Skips decided while
planning (the new Flexible case, `src/engine/reconcile.py` `plan_actions`) are logged
as `skip:<reason>`, but skips raised while acting (H3, `execute_actions`) are logged
as `skipped:<reason>`. Queries that filter on `result startswith "skipped"` —
including the day-2 workbook's **"Failed or skipped"** panel — therefore miss
Flexible scale set skips.

- [x] Use `skipped:<reason>` for plan-time skips too (one prefix everywhere).
- [x] Update the reconcile tests that assert `skip:vmss-flexible-unsupported`.
- [x] Confirm the cycle summary's `skipped` count includes plan-time skips.
- [x] Live check (2026-10-07): a throwaway 1-instance **Flexible** scale set
  `vmss-demo-v3flex` (dev, `rg-demo-vmss`), tagged `schedule-profile=weekday-0830-1730`,
  logged `result=skipped:vmss-flexible-unsupported` (`action=none`, `actual=Unknown`)
  across 6 consecutive cycles (05:45–07:00 UTC) — **not** `state-read-failed`, and
  the summary `skipped` count included it (no `failed`). Deleted afterwards.

#### V5 — custom role missing scale-set VM read action; VMSS re-submits start every cycle

| | |
|---|---|
| **Severity** | High |
| **Status** | ✅ Fixed and **confirmed live** (demo 2026-10-07): W6 converged to `actualState=Running`, `action=none` |
| **Found** | 2026-10-07, first live business morning (Phase B), W6 (`vmss-demo-w6`) |
| **Location** | `infra/modules/rbac/main.tf` (vmss action set); `src/handlers/vmss.py` (`get_state`); REQUIREMENTS §11.1 |
| **Related** | V2, V3, HR-008, SEC-002, FR-004 |

**Description.** From the 01:30 UTC (08:30 Bangkok) start boundary, W6 logged
`actualState=Stopped`, `action=start`, `result=submitted` **every** cycle even
though its instance was `PowerState/running` — the engine kept re-submitting
`start` because it never saw the scale set as running.

**Root cause.** The custom role **Resource Power Operator** granted
`Microsoft.Compute/virtualMachineScaleSets/read` but **not**
`Microsoft.Compute/virtualMachineScaleSets/virtualMachines/read`. The `vmss`
handler reads power state from the per-instance view (Uniform scale sets carry
no power state on the scale-set resource — V2/V3). Without the child read action
ARM **authorization-filters the instance list to empty** (an empty collection,
not a 403), so the handler hit its "no instances → capacity 0 → `deallocated`"
branch and reported `Stopped`. Overnight this happened to be correct (W6 was
genuinely deallocated); after the morning start it was wrong, causing the churn.
Confirmed by querying Resource Graph (`powerState=""` for the VMSS → handler
fallback used) and by running the handler's SDK calls as a privileged identity
(1 instance, `PowerState/running`) vs. the managed identity (empty list).

**Fix.**
1. **RBAC (resolves the live symptom):** added
   `Microsoft.Compute/virtualMachineScaleSets/virtualMachines/read` to the `vmss`
   action set (`infra/modules/rbac/main.tf`) and REQUIREMENTS §11.1. Applied to
   the demo tenant: `0 add / 1 change / 0 destroy` (role definition updated
   in-place; no assignments touched).
2. **Handler robustness (prevents silent recurrence):** `get_state` now reads the
   scale set's `sku.capacity` from the single `virtual_machine_scale_sets.get`
   it already makes for orchestration mode. If no instance power states are
   readable **but capacity > 0**, it returns `unknown` (engine logs
   `unknown-state-skip` and does not act) instead of silently assuming
   `deallocated`. Genuine capacity 0 still returns `deallocated`.

**Acceptance criteria.**
- [x] Custom role includes `virtualMachineScaleSets/virtualMachines/read` (verified live via `az role definition list`).
- [x] Unit test: empty instance list with capacity > 0 → `unknown` (`test_vmss_v5_empty_list_but_capacity_present_is_unknown`); genuine capacity 0 → `deallocated` (`test_vmss_no_instances_is_deallocated`). Suite 162 passed / 8 skipped; strict SDK-surface 8 passed; ruff clean.
- [x] Live: after applying the role change and re-publishing the code, W6 reads `actualState=Running`, `action=none`, `result=already-converged` (demo 2026-10-07, 04:00:03 UTC cycle), ending the per-cycle `start` churn.

**Review follow-up (2026-10-07).** The reviewer flagged that the first fix was
**incomplete**: the handler's fallback also calls
`virtual_machine_scale_set_vms.get_instance_view(...)` (when
`list(expand="instanceView")` does not inline an instance's power state), which
needs a **second** action — `Microsoft.Compute/virtualMachineScaleSets/virtualMachines/instanceView/read`
— beyond the `.../virtualMachines/read` needed to list instances. Added that
action to the role (`29ad8fb`) + REQUIREMENTS §11.1 (`80a303d`) and **applied it
live** (demo `0 add / 1 change / 0 destroy`; `az role definition list` now shows
all three vmss read actions; re-plan "No changes"). The reviewer also added
`tests/test_rbac_consistency.py`, which statically scans each handler for its SDK
calls and asserts the custom role grants the matching ARM action — so role/SDK
drift (the V5 root cause) now fails CI. Full suite **172 passed / 8 skipped**
(the +10 are the new consistency checks).

### 6.2 Tooling notes found during verification

These are documentation/tooling observations. V4 (below) is now **implemented**:
the CLI snippets in the README and §3.4 query the Log Analytics workspace, while
the alerts, workbook and portal queries stay on the classic App Insights schema.

#### V4 — `az monitor app-insights query` returns no rows (workspace-based App Insights)

| | |
|---|---|
| **Severity** | Low (tooling / docs; no product impact) |
| **Status** | ✅ Fixed (2026-10-07) — CLI tooling switched to the workspace; alerts, workbook and portal queries unchanged |
| **Found** | 2026-10-06, while collecting the morning start-window evidence (dry-run) |
| **Location** | README Step 6; VERIFICATION §3.3/§3.4 (all queries); `demo/scripts/collect-evidence.sh` |

**Description.** The documented evidence queries use
`az monitor app-insights query --app appi-pwrsched …`. Against the demo
scheduler this returns **zero rows** even for an unfiltered `traces | take`.
`appi-pwrsched` is a **workspace-based** Application Insights (linked to the Log
Analytics workspace `log-pwrsched`), so telemetry is stored in the workspace, in
the **`AppTraces`** table with custom dimensions under **`Properties[...]`** —
not in the classic `traces` / `customDimensions` the app-insights CLI reads. The
Azure Portal "Logs" blade works because it queries the workspace directly.

**Confirmed.** `az monitor app-insights component show` reports
`workspace: …/workspaces/log-pwrsched`. Querying the workspace returns the data:

```bash
# workspace GUID (customerId) of log-pwrsched
WS=$(az monitor log-analytics workspace show \
  -g rg-pwrsched-southeastasia --workspace-name log-pwrsched \
  --query customerId -o tsv)

az monitor log-analytics query --workspace "$WS" --analytics-query '
AppTraces
| where TimeGenerated > ago(1h)
| where tostring(Properties["pwrsched.event"]) == "pwrsched.decision"
| take 20'
```

Translation from the documented KQL: table `traces` → `AppTraces`,
`customDimensions["pwrsched.*"]` → `Properties["pwrsched.*"]`, `timestamp` →
`TimeGenerated`.

**Decision (review 2026-10-06).** The impact is limited to the command line:
all four alert rules are scoped to the Application Insights resource
(`scopes = [azurerm_application_insights.this.id]`), and queries in that scope —
alerts, the portal Logs blade opened from Application Insights, and the day-2
workbook — still work with `traces` / `customDimensions` (the workbook shows data).
Only `az monitor app-insights query` returns nothing.

- [x] **Switch the CLI tooling to the workspace:** README Step 6 (CLI part), the
  §3.3 one-liner, the §3.4 `q()` helper and `demo/scripts/collect-evidence.sh` now use
  `az monitor log-analytics query --workspace <customerId>` with `AppTraces`,
  `Properties["pwrsched.*"]` and `TimeGenerated` (and `AppRequests` /
  `OperationName` for Query 3). The script translates the saved `.kql` files to
  the workspace schema on the fly, so the files stay portal/workbook-ready.
- [x] **Keep unchanged:** the alert rules, the workbook and the portal queries
  (`traces` / `customDimensions` in the Application Insights scope).
- [x] **Add a short note** in README Step 6 and §3.4 explaining the two table schemas, so
  nobody "fixes" the alerts by switching them to `AppTraces`.
- [x] H2 (S15) proves the alerts fire live with the current queries (demo 2026-10-06).

**Note.** This is tooling only. The telemetry itself is correct and complete
(H1/N3/N6 observed via the workspace query — see the 2026-10-06 results-log row).
