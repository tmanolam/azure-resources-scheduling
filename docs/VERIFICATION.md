# Verification Runbook

| Item | Value |
|---|---|
| Document ID | AZ-PWRSCHED-VERIFY-001 |
| Related | [REQUIREMENTS.md](REQUIREMENTS.md), [DEMO_TENANT_PLAN.md](DEMO_TENANT_PLAN.md), [../README.md](../README.md), [archived implementation docs](archive/README.md) |
| Last updated | 2026-10-04 |
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
| OI-01 | Real `in_scope_management_group_ids` and `excluded_scope_ids` in `terraform.tfvars` | [§2](#2-prerequisites-for-a-live-deploy-t-602t-603) | ⛔ Blocks T-602 |
| T-602 | Deploy and dry-run validation | [§3](#3-deploy--dry-run-validation-t-602) | ⬜ Not started |
| T-603 | Go-live | [§4](#4-go-live-t-603) | ⬜ Not started (needs T-602, all live checks below, and V1 fixed) |
| V1 | AKS-managed node pool scale sets are not excluded from scheduling | [§6.1](#61-issues-found-during-verification) | 🔍 Fixed in code — live check pending (demo scenario S18) |

### Live checks carried over from the code review

Each of these is fixed in code but can only be confirmed on a deployed app. All
must pass before T-603. Background on each ID is in
[archive/REVIEW_FINDINGS.md](archive/REVIEW_FINDINGS.md).

| ID | Live check | Where | Status |
|---|---|---|---|
| C1 | Resources in prod subscriptions logged as `production-excluded`, never acted on | [§3.3](#33-dry-run-checklist-one-cycle--15-min) | 🔍 Pending |
| C3 | SQL MI `actualState` never `Unknown` | [§3.4](#34-live-verification-of-review-findings), Query 2 | 🔍 Pending |
| H1 | Decision records carry all OBS-001 fields | §3.4, Query 1 | 🔍 Pending |
| H2 | Cycle-health and cycle-exceptions alerts fire | [§5](#5-alert-verification-obs-003004005) | 🔍 Pending |
| M4 | Timer fires on schedule; past-due recovery; no storage auth errors | §3.4, Queries 3–5 | 🔍 Pending |
| N3 | Summary count matches invocation count | §3.4, Queries 3 and 6 | 🔍 Pending |
| N4 | Mixed-case RG profile inheritance | §3.4, Query 7 | 🔍 Pending |
| N6 | `dryRun` stored as `true` | §3.4, Query 1 | 🔍 Pending |

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
