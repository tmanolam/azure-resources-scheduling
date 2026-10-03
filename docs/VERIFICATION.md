# Verification Runbook

| Item | Value |
|---|---|
| Document ID | AZ-PWRSCHED-VERIFY-001 |
| Related | [REQUIREMENTS.md](REQUIREMENTS.md), [PHASE1_TASKS.md](PHASE1_TASKS.md), [../README.md](../README.md) |
| Scope | How to verify the scheduler — static checks (T-601), live dry-run (T-602), go-live (T-603) |

This runbook is the repeatable procedure behind Phase 6. T-601 runs offline (and
in CI); T-602/T-603 require a live Azure tenant.

---

## 1. Static checks & unit tests (T-601)

No cloud access required. Run from the repo root.

### 1.1 Python unit tests (NFR-009)

```bash
python -m pip install pytest tzdata     # once
python -m pytest -q
```

**Expected:** all tests pass (currently **102 passed**). The suite covers the
pure evaluator (timezones, midnight crossing, overrides), discovery paging,
selection (production hard-exclusion, tag precedence), ordering/safety, the
reconcile orchestrator (dry-run, 429 back-off), the 7 handlers, telemetry field
contract, and the App Configuration loader + runtime assembly.

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

The same two checks run automatically on every push / PR to `main` via
`.github/workflows/ci.yml` (jobs: **Python unit tests**, **Terraform fmt +
validate**). CI performs **no deployment** and needs no cloud credentials.

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
Functions in func-pwrsched:
    reconcile - [timerTrigger]
```

### 3.3 Dry-run checklist (one cycle ≈ 15 min)

Query Application Insights (README Step 6 shows the full KQL):

```bash
APPI=$(terraform -chdir=../infra/scheduler output -raw application_insights_name)
RG=$(terraform -chdir=../infra/scheduler output -raw resource_group_name)
az monitor app-insights query --app "$APPI" --resource-group "$RG" \
  --analytics-query 'traces | where customDimensions.event == "pwrsched.decision" | take 50'
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
| OBS-004 repeated failures | `pwrsched.decision` with `result == "failed"` for the same `resourceId` across 3 runs |
| OBS-005 cap reached | a `pwrsched.capReached` event |

Field alignment between emitted telemetry and the alert/README KQL is checked by
the unit tests (`tests/test_telemetry.py`) and was verified to have **0 gaps**.
To exercise an alert in a test tenant, temporarily lower `max_actions_per_run`
to force a `pwrsched.capReached` event and confirm the action group fires.
