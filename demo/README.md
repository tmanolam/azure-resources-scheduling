# Demo Tenant Runbook

> Step-by-step guide to build, verify and demonstrate the Azure Resource Power
> Scheduler in a disposable demo tenant. This is the operational companion to
> the plan in [DEMO_TENANT_PLAN.md](../docs/archive/demo-verification/DEMO_TENANT_PLAN.md); it tells
> you **what to run, in what order**. The demo is built and verified (Phase B closed
> 2026-10-07): the task tracker and the full verification record are archived in
> [docs/archive/demo-verification/](../docs/archive/demo-verification/VERIFICATION.md).
> In this runbook, "VERIFICATION §…" means that archived demo record.

| Item | Value |
|---|---|
| Plan | **Plan A** — four subscriptions on the credit (DEMO_TENANT_PLAN §2.1) |
| Region | `southeastasia` (matches the profiles' Asia/Bangkok timezone) |
| Product code | **unchanged** — the demo uses `infra/scheduler` + `src/` as shipped; everything demo-specific is under `demo/` |

> ⚠️ This builds **real Azure resources** that cost money against the credit.
> Follow the budget guidance (§4.3 of the plan) and tear everything down (§7
> here) when done.

---

## Contents

- [Folder layout](#folder-layout)
- [Order of operations](#order-of-operations)
- [1. Prerequisites](#1-prerequisites)
- [2. Landing zone](#2-landing-zone)
- [3. Workloads](#3-workloads)
- [4. Scheduler (dry-run)](#4-scheduler-dry-run)
- [5. Verify in dry-run (Phase A)](#5-verify-in-dry-run-phase-a)
- [6. Go live and run scenarios (Phase B)](#6-go-live-and-run-scenarios-phase-b)
- [7. Collect evidence and demo](#7-collect-evidence-and-demo)
- [8. Teardown](#8-teardown)
- [Scenario → script → query map](#scenario--script--query-map)

---

## Folder layout

```
demo/
├── README.md                  # this runbook
├── .gitignore                 # ignores evidence/, real *.tfvars, state
├── landing-zone/              # MGs, subscription placement + tags, budgets (DM-10–DM-14)
│   ├── main.tf providers.tf variables.tf budgets.tf outputs.tf
│   ├── render-demo-tfvars.sh  # generates infra/tenants/demo.tfvars from outputs
│   ├── backend.hcl.example    # remote state template (DEMO_STATE_BACKEND.md)
│   └── terraform.tfvars.example
├── workloads/                 # W1–W14 with toggles (DM-20–DM-23)
│   ├── providers.tf variables.tf network.tf
│   ├── workloads_vms_dev.tf workloads_db_vmss.tf workloads_vms_other.tf workloads_optional.tf
│   ├── backend.hcl.example    # remote state template (DEMO_STATE_BACKEND.md)
│   ├── outputs.tf terraform.tfvars.example
├── scheduler/
│   └── demo.tfvars.example    # §2.3 values for infra/scheduler (DM-30)
├── queries/                   # saved KQL: Q-A…Q-G + verification-3.4-queries.kql (DM-41)
└── scripts/
    ├── register-providers.sh      # DM-05
    ├── lib/common.sh
    ├── scenario-*.sh              # one per scenario action (DM-40)
    ├── collect-evidence.sh        # DM-42
    └── teardown.sh                # DM-43
```

---

## Order of operations

```
Prereqs (manual) → landing-zone apply → workloads apply → scheduler deploy (dry-run)
   → Phase A verify (≥ 1 business day) → go live → Phase B scenarios
   → collect evidence → stakeholder demo → teardown
```

All Terraform here uses a **remote azurerm backend** (`demosatfstate` — see
[docs/DEMO_STATE_BACKEND.md](../docs/DEMO_STATE_BACKEND.md)). Run commands from
the repo root unless noted. Sign in to the **demo tenant** first:

```bash
az login --tenant <demo-tenant-id>
export ARM_TENANT_ID=<demo-tenant-id>
```

---

## 1. Prerequisites

Manual steps (DEMO_TENANT_PLAN §3). Status is recorded in the archived [DEMO_TASKS.md](../docs/archive/demo-verification/DEMO_TASKS.md).

| Ref | Step |
|---|---|
| DM-01/02 | Create the demo tenant, activate the credit, confirm the credit allows four subscriptions (Plan A) and `southeastasia` |
| DM-03 | Create and rename the four subscriptions (§2.1) — `sub-demo-sandbox` may come later |
| DM-04 | Elevate access (Entra ID → Properties → Access management = Yes), re-login |
| DM-05 | Register resource providers in each subscription (script below) |
| DM-06 | Check vCPU quota in `southeastasia` (≥ 10 B-series) |
| DM-07 | Check SQL MI free-offer eligibility (decides W14 funding) |

Register providers (idempotent; re-run for sandbox once it exists):

```bash
./demo/scripts/register-providers.sh \
  <sub-demo-management> <sub-demo-workload-dev> <sub-demo-workload-prod>
# later: ./demo/scripts/register-providers.sh <sub-demo-sandbox>
```

---

## 2. Landing zone

Creates the management-group hierarchy, places the subscriptions, tags them
(incl. the deliberately mixed-case `Environment=Prod` on the prod subscription),
and sets budget alerts (DM-10–DM-14).

```bash
cd demo/landing-zone
cp terraform.tfvars.example terraform.tfvars
cp backend.hcl.example backend.hcl   # remote state (demosatfstate); gitignored
# edit terraform.tfvars: the four subscription IDs (sandbox may stay empty),
# mg_prefix (default "demo"), budget_contact_emails

terraform init -backend-config=backend.hcl
terraform plan -out tfplan
terraform apply tfplan
cd ../..
```

**Checkpoint:** the MG hierarchy from §2.2 is visible in the portal; the prod
subscription shows `Environment=Prod`.

Generate the scheduler's `demo.tfvars` from the landing-zone outputs:

```bash
demo/landing-zone/render-demo-tfvars.sh --alert-email you@example.com
# writes infra/tenants/demo.tfvars (gitignored)
```

---

## 3. Workloads

Deploys W1–W11 (core) and, optionally, W12–W14. Keep the optional components
**off** during the Phase A dry-run week to control cost.

```bash
cd demo/workloads
cp terraform.tfvars.example terraform.tfvars
cp backend.hcl.example backend.hcl   # remote state (demosatfstate); gitignored
# edit: subscription IDs; sandbox id if it exists;
# enable_aks/appgw/sqlmi = false for now

terraform init -backend-config=backend.hcl
terraform plan -out tfplan
terraform apply tfplan
cd ../..
```

**Checkpoint:** `terraform output workload_resource_groups` lists the RGs;
`RG-Demo-MixedCase` (W2) keeps its exact casing. No secrets appear in outputs.

> If `sub-demo-sandbox` does not exist yet, W10 is skipped automatically and the
> output says so. Run scenario S3 later once the subscription is created and its
> ID is set in `terraform.tfvars`.

> **Outbound access (DR-10):** Azure is phasing out default outbound internet
> access for new VNets. The demo VMs have no public IP and rely on default
> outbound, which `az vm run-command` (scenario S11) and in-guest package
> updates may need. After deploy, verify with:
> `az vm run-command invoke -g rg-demo-poweroff -n vm-demo-w5 --command-id RunShellScript --scripts "curl -sI https://management.azure.com | head -1"`.
> If it fails, add a NAT gateway on the dev subnet (small extra cost) — the
> scheduler itself does not need VM outbound, only the S11 run-command does.

---

## 4. Scheduler (dry-run)

Deploy the shipped scheduler into the demo tenant using the per-tenant wrapper,
which selects the demo var-file and state backend and reinitialises the backend
safely for this tenant. You need a Terraform **state backend** for the demo
(README Step 2) and the two demo tenant files.

```bash
cd infra/tenants
cp demo.tfvars.example      demo.tfvars        # or generate it (see §2)
cp demo.backend.hcl.example demo.backend.hcl   # fill the demo state storage account
cd ../..

# Sign in to the demo tenant first (deploy.sh re-inits the backend, not your CLI session).
./infra/deploy.sh demo plan
```

> `demo.tfvars` can also be generated from the landing-zone outputs:
> `demo/landing-zone/render-demo-tfvars.sh --alert-email you@example.com`
> writes `infra/tenants/demo.tfvars` directly.

**Checkpoint — plan review (R-01 safety):** the plan creates the custom-role
assignment **only** at `demo-landingzones` and `demo-sandbox` — never at the
Tenant Root, `demo` root, or `demo-platform`. Then apply:

```bash
./infra/deploy.sh demo apply
```

Publish the function code:

```bash
cd src
FUNC_APP=$(terraform -chdir=../infra/scheduler output -raw function_app_name)
func azure functionapp publish "$FUNC_APP" --python
cd ..
```

**Checkpoint:** the publish log ends with `reconcile - [timerTrigger]`.

---

## 5. Verify in dry-run (Phase A)

This is **VERIFICATION §3** (T-602). Let the scheduler run; `dry_run` stays
`true`. Run the dry-run scenarios (S1–S3, S6–S9, S13, S15, S16) and the §3.4
checks. Collect a labelled evidence set:

```bash
demo/scripts/collect-evidence.sh phase-a
```

Confirm against the VERIFICATION §3.3/§3.4 checklist: summaries every cycle,
only in-scope tagged resources, **no Platform MG** resources, prod shows
`production-excluded`, `dryRun = true`, no Activity-Log actions. Update the
VERIFICATION §0 tracker and §6 results log.

Alert tests (S15 / finding H2), run in dry-run and restore afterwards:

```bash
RG=$(terraform -chdir=infra/scheduler output -raw resource_group_name)
FUNC_APP=$(terraform -chdir=infra/scheduler output -raw function_app_name)

# cycle-exceptions alert
demo/scripts/scenario-appconfig-endpoint.sh break   --rg "$RG" --app "$FUNC_APP"
# ... confirm the alert fires, then:
demo/scripts/scenario-appconfig-endpoint.sh restore --rg "$RG" --app "$FUNC_APP" \
  --endpoint "$(terraform -chdir=infra/scheduler output -raw app_configuration_endpoint)"

# past-due recovery (S16 / M4)
demo/scripts/scenario-funcapp-restart.sh --rg "$RG" --app "$FUNC_APP"
```

---

## 6. Go live and run scenarios (Phase B)

After **≥ 1 full business day** of correct dry-run results (VERIFICATION §4 /
T-603). Enable the optional components first if budgeted:

```bash
# in demo/workloads/terraform.tfvars: enable_aks = true, enable_appgw = true
#   (enable_sqlmi = true LAST, destroy after S17 — see §4.3 budget)
terraform -chdir=demo/workloads apply
```

Flip the scheduler to live:

```bash
# in infra/tenants/demo.tfvars: dry_run = false
./infra/deploy.sh demo plan     # only change: pwrsched:dryRun → false
./infra/deploy.sh demo apply
```

Run the live scenarios with the scripts (see the [map](#scenario--script--query-map)):

```bash
DEV=<sub-demo-workload-dev-id>
RG=$(terraform -chdir=infra/scheduler output -raw resource_group_name)
FUNC_APP=$(terraform -chdir=infra/scheduler output -raw function_app_name)

# S4 — work late: keep rg-demo-override running until 19:00 Bangkok
demo/scripts/scenario-override.sh set \
  --target "/subscriptions/$DEV/resourceGroups/rg-demo-override" --state running --hours 2

# S5b — ad-hoc start of W1 for 1 hour (evening/weekend)
demo/scripts/scenario-override.sh set \
  --target "/subscriptions/$DEV/resourceGroups/rg-demo-vm" --state running --hours 1

# S10 — drift: start the PostgreSQL server out of hours
demo/scripts/scenario-start-db.sh --subscription "$DEV"

# S11 — powered-off (not deallocated) VM
demo/scripts/scenario-poweroff-vm.sh --subscription "$DEV"

# S14 — action cap: set cap=2, override the dev subscription, watch capReached
# The App Configuration name is not a scheduler output; derive it from the endpoint
# (https://<name>.azconfig.io).
APPCS_EP=$(terraform -chdir=infra/scheduler output -raw app_configuration_endpoint)
APPCFG=$(echo "$APPCS_EP" | sed -E 's#https://([^.]+)\..*#\1#')
demo/scripts/scenario-cap.sh set --appconfig "$APPCFG" --value 2
demo/scripts/scenario-override.sh set --target "/subscriptions/$DEV" --state running --hours 1
# ... after the cap alert fires:
demo/scripts/scenario-cap.sh restore --appconfig "$APPCFG"
demo/scripts/scenario-override.sh clear --target "/subscriptions/$DEV"
```

> Clean up each override when the scenario is done (`scenario-override.sh clear
> --target …`), and restore any config you changed, so Terraform stays the
> source of truth.

---

## 7. Collect evidence and demo

Collect a final labelled evidence set once a full live weekday plus the override
scenarios are in the logs:

```bash
demo/scripts/collect-evidence.sh phase-b
```

The stakeholder demo (DEMO_TENANT_PLAN §8) is **logs-only** — nothing is changed
live. Open Application Insights → Logs and run the saved queries in order:

| # | File | Shows |
|---|---|---|
| Q-A | `queries/Q-A_day_timeline.kql` | The day runs itself, in dependency order |
| Q-B | `queries/Q-B_cycle_detail.kql` | Every decision explained and auditable |
| Q-C1 | `queries/Q-C1_production_excluded.kql` | Production skipped every cycle |
| Q-C2 | `queries/Q-C2_platform_absent.kql` | Platform resources never acted on (empty) |
| Q-D | `queries/Q-D_overrides.kql` | Owners extend hours without a ticket |
| Q-E | `queries/Q-E_self_healing.kql` | Drift corrected automatically |
| Q-F | `queries/Q-F_cycle_health.kql` | Steady, observable, safe to operate |
| Q-G | `queries/Q-G_hours_saved.kql` | The business case, from real data |

> Set the `datetime(...)` window in Q-A/Q-D to a live weekday (UTC). Bangkok
> 08:00 = 01:00 UTC; 17:30 = 10:30 UTC. Keep App Insights retention at the
> default 90 days so the data is still there when you present.

---

## 8. Teardown

Follow DEMO_TENANT_PLAN §9. The script does the three Terraform destroys and
reminds you of the manual steps:

```bash
# 1. Stop actions first: set dry_run = true in infra/tenants/demo.tfvars and apply
./infra/deploy.sh demo plan && ./infra/deploy.sh demo apply

# 2. Export evidence if you want to keep it
demo/scripts/collect-evidence.sh final

# 3. Destroy workloads → scheduler → landing zone (asks for confirmation)
demo/scripts/teardown.sh
```

Then the **manual** steps the script reminds you about:
- Remove the subscription tags left by the landing zone (DR-11): `terraform
  destroy` does not clear `environment` / `schedule-profile` set via
  `azapi_update_resource`. Delete them with
  `az tag update --operation Delete --resource-id /subscriptions/<id> --tags environment schedule-profile`
  on each demo subscription.
- Delete the demo-only state storage account.
- Turn **off** elevated access (DM-04).
- Cancel the subscriptions when the tenant is no longer needed.

---

## Scenario → script → query map

| Scenario | Script | Evidence query | VERIFICATION |
|---|---|---|---|
| S1 daily schedule | (none — watch the clock) | Q-A, Q-B | H1, N6 |
| S2 RG inheritance (mixed-case) | (W2 is pre-tagged) | verification-query-7 | N4 |
| S3 subscription inheritance | (W10 inherits sub tag) | Q-B | — |
| S4 override: work late | `scenario-override.sh set --state running` | Q-D | — |
| S5 override: stop early | `scenario-override.sh set --state stopped` | Q-D | — |
| S5b override: ad-hoc start | `scenario-override.sh set --state running` | Q-B | — |
| S6 opt-out | (W4 pre-tagged `schedule-enabled=false`) | Q-B | — |
| S7 production exclusion | (W9 in prod subscription) | Q-C1 | C1, N5 |
| S8 platform exclusion | (W11 under Platform MG) | Q-C2 | — |
| S9 nested MG exclusion | `scenario-move-sandbox-mg.sh exclude/restore` | Q-B | — |
| S10 drift correction | `scenario-start-db.sh` | Q-E | — |
| S11 powered-off VM | `scenario-poweroff-vm.sh` | Q-E | H4 |
| S12 dependency ordering | (watch S1L window) | Q-A | — |
| S13 telemetry health | (leave running ≥ 3h) | verification-query-3/4/6 | M4, N3 |
| S14 action cap | `scenario-cap.sh set/restore` + override | Q-F | OBS-005 |
| S15 alerts | `scenario-appconfig-endpoint.sh`; `scheduler_enabled=false` | Q-F | H2 |
| S16 past-due recovery | `scenario-funcapp-restart.sh` | verification-query-5 | M4 |
| S17 SQL MI (if W14) | (included in S1L) | verification-query-2 | C3 |
| S18 AKS node pool protection (if W12) | tag `rg-demo-aks-nodes` `schedule-profile=...`; watch 2 cycles; untag | Q-B (filter node RG) | V1 / HR-007 |
