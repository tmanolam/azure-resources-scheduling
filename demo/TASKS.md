# Demo Tenant Build — Task Breakdown

> Working task tracker for the `demo/` build (DM-10–DM-44). Decomposes the
> implementation tasks in [DEMO_TENANT_PLAN.md §5](../docs/DEMO_TENANT_PLAN.md)
> into concrete subtasks, each flagged by whether it can be built **offline now**
> or **needs the live demo tenant**. Mirrors the archived
> [PHASE1_TASKS.md](../docs/archive/PHASE1_TASKS.md) style.

| Item | Value |
|---|---|
| Document ID | AZ-PWRSCHED-DEMO-TASKS-001 |
| Related | [DEMO_TENANT_PLAN.md](../docs/DEMO_TENANT_PLAN.md), [VERIFICATION.md](../docs/VERIFICATION.md), [REQUIREMENTS.md](../docs/REQUIREMENTS.md) |
| Created | 2026-10-04 |
| Status legend | ⬜ Not started · 🟡 In progress · ✅ Done · ⛔ Blocked |
| Buildability | 🟢 Offline-buildable now (no live tenant) · 🔵 Needs live tenant/subscriptions |

> **Why this doc exists:** the four demo subscriptions (§2.1) are being created
> under an Azure credit with quota limits. `sub-demo-sandbox` is not created yet.
> Everything under `demo/` is **code and docs** that can be authored and
> statically validated (`terraform validate`, `bash -n`, KQL review) **without**
> any subscription existing. This tracker separates that offline work from the
> steps that must wait for the live tenant.

---

## Prerequisites (manual, §3) — status

These are done by the operator, not Kiro. Tracked here for context.

| Ref | Step | Buildability | Status | Notes |
|---|---|---|---|---|
| DM-01 | Create demo tenant + activate credit | 🔵 | ✅ | Operator — tenant `1b0a7c64…` active; deploys succeeded against it (2026-10-05) |
| DM-02 | Confirm credit limits (subscriptions, regions, services, spending limit) | 🔵 | ✅ | 4-subscription Plan A confirmed; 3 subs funded (sandbox pending). Note: `southeastasia` had **no VM capacity** for B-series (not a quota issue — regional vCPU limit 65, usage 0); workloads moved to `eastasia` |
| DM-03 | Create + rename subscriptions (§2.1) | 🔵 | ✅ | All 4 created: management, workload-dev, workload-prod, **`sub-demo-sandbox` (`a8572700-…`, created 2026-10-06)** |
| DM-04 | Elevate access (UAA at Tenant Root), re-login | 🔵 | ✅ | Done — MG/role-assignment/tag operations succeeded. ⏳ Turn off again after full teardown (§9) |
| DM-05 | Register resource providers in each subscription | 🔵 | ✅ | All 12 providers Registered on all 4 subs (sandbox confirmed 2026-10-06: Compute, Network, Storage verified via `az provider show`) |
| DM-06 | Check vCPU quota in `southeastasia` (≥10 B-series) | 🔵 | ✅ | Quota fine (65 vCPUs). But B-series had a **capacity restriction** in `southeastasia`/`eastasia`; `Standard_B2ts_v2` has capacity in `eastasia` — workloads deployed there with that size |
| DM-07 | Check SQL MI free-offer eligibility | 🔵 | ⬜ | Decides W14 funding (W14 not yet deployed) |

---

## Progress summary (Kiro build tasks)

| Group | Tasks | Done | Status |
|---|---|---|---|
| Scripts & prerequisites | DM-05, DM-40, DM-42, DM-43 | 4 / 4 | ✅ |
| Landing zone (Terraform) | DM-10–DM-14 | 5 / 5 code + **applied to demo tenant** | ✅ |
| Workloads (Terraform) | DM-20–DM-23 | 4 / 4 code + **core applied (eastasia)** | ✅ |
| Scheduler deployment | DM-30–DM-31 | 2 / 2 — **deployed + code published, dry-run cycle verified** | ✅ |
| Queries & evidence | DM-41, DM-44 | 1 / 2 | 🟡 |
| Runbook | demo/README.md | 1 / 1 | ✅ |
| **Total** | | **17 / 18** | 🟡 |

> **Live status (2026-10-06) — GO-LIVE DONE:** Landing zone (all 4 subs placed, incl. sandbox),
> core workloads (W1–W9, W11 + VMSS + 2 DBs), W10 (sandbox) and **W12 AKS** are deployed. The
> `reconcile` timer runs every 15 min and the scheduler is now **LIVE** (`dry_run=false`, T-603).
> **Completed 2026-10-06:** S1/S12 morning start window **and the 17:30 stop window** (= one full
> business-day dry-run), S3 (sandbox sub inheritance), S9 (nested-MG exclusion), M4 (past-due
> recovery), N4 (mixed-case RG), H2 (both OBS-003 alerts fired live), **S18/V1 (AKS node-pool
> protection verified live → V1 closed)**, and **go-live** (plan showed only `pwrsched:dryRun`;
> first live cycle stopped the AKS cluster via the managed identity, SEC-008; `failed=0`, no
> `capReached`). **Not in scope:** SQL MI (W14 / C3 not tested), App Gateway (W13). **Note:** W12
> node size is `Standard_B2s_v2` (B2s capacity-restricted in eastasia). Reverse-order *stop
> submission* (S12) is observable at the next live 17:30 if evidence is wanted.

---

## What can proceed in parallel right now (🟢)

All of these are code/docs, validated offline — **no subscription required**:

- `demo/README.md` runbook (order of operations, commands, teardown)
- `demo/landing-zone/` Terraform (DM-10, DM-14 outputs/renderer) — authored and `terraform validate`-able with no apply
- `demo/workloads/` Terraform (DM-20–DM-23) — authored and validatable
- `demo/scheduler/demo.tfvars.example` (DM-30) — static template
- `demo/scripts/*` (DM-40, DM-42, DM-43) — bash, `bash -n` checkable
- `demo/queries/*.kql` (DM-41) — KQL authored against the known telemetry contract

Blocked until the live tenant exists (🔵): ~~DM-11, DM-12, DM-13 apply-time behaviour,
DM-31 deploy~~ — **all done 2026-10-05**. ~~Still 🔵: W10 and scenarios needing the
sandbox subscription (S3, S9)~~ — **sandbox created + placed, W10 applied, S3 and S9
verified 2026-10-06**. Still 🔵: the remaining live scenario runs (S10–S18 except S9;
e.g. S18/V1 needs W12) and T-603 go-live. See §8 for the fixes the live deploy required.

---

## 1. Landing zone — `demo/landing-zone/` (DM-10–DM-14)

### DM-10 — Management group hierarchy (§2.2)
- **Buildability:** 🟢 Terraform authorable offline; 🔵 apply needs tenant
- **DoD:** `azurerm_management_group` resources for `demo`, `demo-platform`,
  `demo-platform-management`, `demo-platform-connectivity`, `demo-landingzones`,
  `demo-workload-np`, `demo-workload-prod`, `demo-sandbox`, `demo-sandbox-excluded`,
  `demo-decommissioned`, nested per §2.2. `terraform validate` passes.
- **Status:** ✅ (authored + offline-validated: fmt clean, validate Success!; apply needs tenant)

### DM-11 — Place subscriptions in MGs (§2.1)
- **Buildability:** 🔵 Needs the subscriptions to exist (incl. `sub-demo-sandbox`)
- **DoD:** `azurerm_management_group_subscription_association` for each sub under its MG.
  Terraform **resource** authorable now behind a variable; real IDs needed to apply.
- **Status:** ✅ (code + **applied 2026-10-05**: management/workload-dev/workload-prod placed under their MGs; **sandbox placed under `demo-sandbox` 2026-10-06**, verified via MG entity chain)

### DM-12 — Subscription tags (§2.1)
- **Buildability:** 🔵 Needs subscriptions; code 🟢
- **DoD:** `environment` tags per §2.1 incl. deliberately mixed-case `Environment=Prod`
  (tests N5) and `schedule-profile=sandbox-default` on sandbox. Use `azapi`
  (`Microsoft.Resources/tags`) or `az tag update` (azurerm has no subscription-tag resource).
- **Status:** ✅ (code + **applied 2026-10-05**: `az tag list` confirms `Environment=Prod` on the prod sub (mixed case, N5) and `environment` tags on management/dev; **sandbox tags `environment=sandbox` + `schedule-profile=sandbox-default` applied 2026-10-06**)

### DM-13 — Budgets + email alerts at USD 250/500/750
- **Buildability:** 🔵 Needs the credit subscription(s); code 🟢
- **DoD:** `azurerm_consumption_budget_subscription` with 3 notifications. Visible in Cost Management after apply.
- **Status:** ✅ (code + **applied 2026-10-05**: 3 budgets created (management/dev/prod) at 250/500/750; **4th budget (sandbox) added 2026-10-06**)

### DM-14 — Outputs + demo.tfvars renderer
- **Buildability:** 🟢 fully offline
- **DoD:** Outputs expose MG + subscription IDs; a script renders
  `infra/tenants/demo.tfvars` from them matching §2.3 (used by `./infra/deploy.sh demo`).
- **Status:** ✅ (`outputs.tf` + `render-demo-tfvars.sh`; bash -n OK; run needs a landing-zone apply first)

---

## 2. Workloads — `demo/workloads/` (DM-20–DM-23)

### DM-20 — Core workloads W1–W11 (§4.1)
- **Buildability:** 🟢 Terraform authorable offline; 🔵 apply needs subs + quota (DM-06)
- **DoD:** W1–W11 with exact tags/placement; **mixed-case RG name `RG-Demo-MixedCase`
  preserved exactly** (S2/N4). VMs: `Standard_B1s`, no public IP, no inbound, generated SSH key.
  One VNet per subscription, no peering. `terraform validate` passes.
- **Status:** ✅ (authored + **applied 2026-10-05**: W1–W9, W11 + VMSS W6 + PostgreSQL W7 / MySQL W8 all running; `RG-Demo-MixedCase` casing preserved. ⚠️ **Deviation from DoD:** `Standard_B1s` was capacity-restricted in `southeastasia` *and* `eastasia`; deployed with `Standard_B2ts_v2` in **`eastasia`** (both set in `demo/workloads/terraform.tfvars`). **W10 sandbox applied 2026-10-06** (`vm-demo-w10` in `rg-demo-sandbox`, eastasia; S3 subscription-inheritance verified))

### DM-21 — Optional toggles (§4.2)
- **Buildability:** 🟢 offline
- **DoD:** `enable_aks`, `enable_appgw`, `enable_sqlmi` (default `false`); each deploys/destroys independently.
- **Status:** ✅ (count-gated W12 AKS / W13 AppGw / W14 SQL MI in `workloads_optional.tf`; apply 🔵)

### DM-22 — Plan B single-subscription support (§2.1)
- **Buildability:** 🟢 offline
- **DoD:** Variable to place all non-prod workloads + sandbox scenarios in one subscription
  using resource groups; same scenarios runnable with one credit subscription.
- **Status:** ⚪ Removed — plan v0.3 dropped Plan B; all four subscriptions use the credit (DR-03). Code removed.

### DM-23 — No public inbound; secrets not output
- **Buildability:** 🟢 offline
- **DoD:** No public inbound access; SSH key + DB passwords generated, never in `terraform output`.
- **Status:** ✅ (NSG with no inbound rules; `tls_private_key`/`random_password` in state only; outputs expose public key + RG names, no secrets)

---

## 3. Scheduler deployment (DM-30–DM-31)

### DM-30 — `demo/scheduler/demo.tfvars.example` (§2.3)
- **Buildability:** 🟢 offline
- **DoD:** Template with §2.3 values; using it with `infra/scheduler` would assign the custom role
  **only** at `demo-landingzones` and `demo-sandbox` (confirmed at plan time once tenant exists).
- **Status:** ✅ (`demo/scheduler/demo.tfvars.example` authored; renderer DM-14 produces the real file)

### DM-31 — Deploy scheduler in dry-run + publish code
- **Buildability:** 🔵 Needs the tenant
- **DoD:** VERIFICATION §3.2 checkpoints pass; `reconcile - [timerTrigger]` listed.
- **Status:** ✅ (**deployed 2026-10-05** via `./infra/deploy.sh demo apply`; R-01 plan check passed — role assigned only at `demo-landingzones` + `demo-sandbox`; code published via `az ... config-zip` remote build; `reconcile - [timerTrigger]` registered; first dry-run cycles emitted decision + summary telemetry with `dryRun=true` and `production-excluded` on W9. Required 4 fixes to deploy — see §8. Outputs: `func-pwrsched-eorw` / `appcs-pwrsched-eorw` / `appi-pwrsched` in `rg-pwrsched-southeastasia`.)

---

## 4. Scripts, queries & evidence (DM-40–DM-44)

### DM-40 — One script per scenario action (§6)
- **Buildability:** 🟢 bash authorable + `bash -n` offline; 🔵 effects need live resources
- **DoD:** Idempotent scripts that print what they changed: set/clear overrides (resource/RG/sub),
  manually start a DB, power off a VM from inside the OS
  (`az vm run-command invoke … sudo poweroff`), toggle `max_actions_per_run`,
  break/restore `APP_CONFIG_ENDPOINT`, stop/start the Function App, move the sandbox
  subscription between MGs.
- **Status:** ✅ (8 scripts + `lib/common.sh`; all `bash -n` clean; effects 🔵 need live resources)

### DM-41 — Saved KQL — `demo/queries/*.kql` (§8)
- **Buildability:** 🟢 fully offline (contract known)
- **Field contract** (from `src/engine/telemetry.py`, bracket-indexed dotted keys):
  - Events: `pwrsched.decision`, `pwrsched.summary`, `pwrsched.capReached`
  - Decision fields: `customDimensions["pwrsched.{runId,resourceId,type,profile,desiredState,actualState,action,dryRun,result,error}"]`
  - Summary fields: `{runId,evaluated,started,stopped,skipped,failed,capReached,durationSeconds}`
  - Booleans are lowercase strings (`dryRun == "true"`), compare with `tolower()` to be safe (N6)
- **DoD:** Queries Q-A…Q-G (§8) authored; each returns data once the demo has run.
- **Status:** ✅ (`Q-A`…`Q-G` + `verification-3.4-queries.kql`; fields verified against telemetry.py + monitoring KQL)

### DM-42 — `collect-evidence.sh <label>`
- **Buildability:** 🟢 authorable offline; 🔵 run needs the deployed app
- **DoD:** Runs VERIFICATION §3.4 Queries 1–7 and the §8 queries, saving output to
  `demo/evidence/<date>-<label>/` (git-ignored).
- **Status:** ✅ (resolves app/RG from TF outputs; awk splitter verified to yield 7 statements; `bash -n` clean)

### DM-43 — `teardown.sh` (§9)
- **Buildability:** 🟢 authorable + `bash -n` offline; 🔵 run needs resources
- **DoD:** Follows §9 order; asks for confirmation before destroying; leaves no billable resources.
- **Status:** ✅ (type-'destroy' confirm or `--yes`; destroys workloads→scheduler→landing-zone; manual steps flagged; `bash -n` clean)

### DM-44 (optional) — Azure Workbook pinning §8 queries
- **Buildability:** 🟢 offline (JSON template)
- **DoD:** Workbook in `demo/` (not `infra/`) for a cleaner demo screen.
- **Status:** ⬜

---

## 5. Runbook — `demo/README.md`

- **Buildability:** 🟢 offline
- **DoD:** Order of operations (prereqs → landing zone → workloads → scheduler → scenarios →
  evidence → teardown), the exact commands, Plan A/B notes, and the teardown sequence (§9).
  Links to DEMO_TENANT_PLAN.md and VERIFICATION.md.
- **Status:** ✅ (`demo/README.md`: order of operations, per-step commands, Plan A, scenario→script→query map, teardown)

---

## 6. Scenario → verification mapping (reference, §7)

Scenarios run against the live tenant (🔵); listed so the scripts/queries above target them.

| Scenario | Covers | Phase | VERIFICATION item |
|---|---|---|---|
| S1, S1L | Daily schedule (dry-run / live) | A / B | H1, N6 |
| S2 | RG inheritance, mixed-case RG | A | N4 |
| S3 | Subscription inheritance | A | — |
| S4, S5, S5b | Overrides (late / early / ad-hoc) | B | — |
| S6 | Opt-out | A | — |
| S7 | Production exclusion | A | C1, N5 |
| S8 | Platform exclusion | A | — |
| S9 | Nested MG exclusion | A | — |
| S10 | Drift correction | B | — |
| S11a/b | Powered-off (not deallocated) VM | B | H4 |
| S12 | Dependency ordering | B | — |
| S13 | Telemetry health | A | M4, N3 |
| S14 | Action cap | B | OBS-005 |
| S15 | Alerts | A | H2 |
| S16 | Past-due recovery | A | M4 |
| S17 | SQL MI (if W14) | B | C3 |
| S18 | AKS node pool protection | A | V1 |

---

## 7. Review findings — demo scaffold (2026-10-04)

Code review of `b963585` (demo scaffold). IDs use the prefix **DR-** (demo
review) because these are defects in the demo code, not live verification
issues (`V` prefix, VERIFICATION §6.1). Fix them before DM-31 (first scheduler
deploy) unless noted. The V1 product fix (`eb0cdd3`) was reviewed separately
and is correct; its live check is S18.

**Round 2** (2026-10-04, re-review of `66bd678` + `4f1f6b9`): DR-01–DR-06,
DR-08, DR-09 and DR-11 confirmed fixed; DR-07 reopened; DR-12–DR-14 added.
Fix DR-07 and DR-12 before first use (DM-31 and teardown).

**Status legend:** 🔴 Open · 🟡 In progress · ✅ Fixed · 🔍 Verify live · ⚪ Won't fix (reason)

| ID | Severity | Finding | Recommended fix | Status |
|---|---|---|---|---|
| DR-01 | High | **Wrong `-var-file` paths and unsafe scheduler teardown.** With `terraform -chdir=infra/scheduler`, a relative `-var-file` resolves against `infra/scheduler`, so `../demo/scheduler/demo.tfvars` points to `infra/demo/…`. Teardown also destroyed `infra/scheduler` against whatever backend that folder was last initialised with. | Deploy/destroy via `./infra/deploy.sh demo <cmd>` (re-inits the demo backend). | ✅ Fixed — added `infra/tenants/demo.{tfvars,backend.hcl}.example`; README §4/§6/§8 + renderer + `teardown.sh` use `deploy.sh demo`; `demo/scheduler/demo.tfvars.example` is now a MOVED pointer. |
| DR-02 | High | **SQL MI `license_type = "BasePrice"`** (Azure Hybrid Benefit), likely non-compliant in a fresh demo tenant. | `LicenseIncluded`. | ✅ Fixed — `license_type = "LicenseIncluded"`. |
| DR-03 | Medium | **Plan B still implemented** although removed in plan v0.3. Under Plan B, W11 would land in an in-scope subscription. | Remove all Plan B code and text. | ✅ Fixed — removed `plan_b` var, alias switching, `separate_management`, `plan` output, tfvars/README/teardown text; DM-22 marked removed. Round 2: one leftover — DM-02's note in this file still says "Decides Plan A vs Plan B". |
| DR-04 | Medium | **Q-G (hours saved) counts dry-run cycles**; Q-A same when replaying a live day. | Filter `dryRun == "false"`. | ✅ Fixed — filter added to Q-G and Q-A. |
| DR-05 | Medium | **App Gateway exposes a public port-80 listener**, contradicting DM-23. | NSG allowing only GatewayManager + AzureLoadBalancer. | ✅ Fixed — `nsg-demo-appgw` (GatewayManager 65200–65535, AzureLoadBalancer, Deny Internet) + subnet association. |
| DR-06 | Low | **Most workload RGs also carry `schedule-profile`**, not only W2's. | Tag only `RG-Demo-MixedCase` (W2) at RG level. | ✅ Fixed — RG-level profile tag removed from W1/W3–W14 RGs; only W2's RG keeps it. |
| DR-07 | Low | **MySQL Flexible doesn't explicitly disable public network access.** | Set `public_network_access = "Disabled"`. | ✅ Fixed (round 2) — set `public_network_access = "Disabled"` on `azurerm_mysql_flexible_server.w8`; verified settable on the pinned azurerm 4.81.0 (`terraform validate` passed with the attribute). Parity with PostgreSQL W7. |
| DR-08 | Low | **`budget_subscription_ids`** described as deprecated/unused in brand-new code. | Remove it. | ✅ Fixed — variable removed. |
| DR-09 | Low | **Q-C ends Part 1 with `;`** then a commented Part 2; trailing separator may not parse. | Split into two files. | ✅ Fixed — `Q-C1_production_excluded.kql` + `Q-C2_platform_absent.kql`; combined file removed; README updated. |
| DR-10 | Low | **Outbound access from demo VMs** may be unavailable (default outbound being phased out); `az vm run-command` (S11) could fail. | Verify after deploy; NAT gateway fallback. | 🔍 Verify — documented in README §3 (verify command + NAT fallback). Live check. |
| DR-11 | Low | **Subscription tags not removed on destroy** (`azapi_update_resource`). | Manual cleanup step. | ✅ Fixed (documented) — `teardown.sh` step 6 + README §8 give the `az tag update --operation Delete` cleanup. |
| DR-12 | Medium | **`./infra/deploy.sh <tenant> destroy` always fails** (product script, affects real tenants too). It runs `terraform destroy -input=false` without `-auto-approve`; with `-input=false` Terraform cannot ask for approval and cancels. Teardown step 4 therefore stops with an error (fails safe: nothing destroyed). Same pattern M7 fixed for `apply`. | Drop `-input=false` from the `destroy` branch only, so Terraform shows its normal "yes" prompt. Keep the plan-file flow for `apply`. | ✅ Fixed — `destroy` branch now runs `terraform destroy -var-file=…` (no `-input=false`); interactive prompt restored. `bash -n` clean. |
| DR-13 | Low | **Stale settings-file path in docs.** After DR-01 the demo scheduler settings file is `infra/tenants/demo.tfvars`, but `docs/DEMO_TENANT_PLAN.md` §2.3 and DM-14, and DM-14 in this file, still say `demo/scheduler/demo.tfvars`. | Update the three references to `infra/tenants/demo.tfvars` (and mention `./infra/deploy.sh demo`). | ✅ Fixed — DEMO_TENANT_PLAN §2.3 + DM-14 row and TASKS DM-14 DoD updated to `infra/tenants/demo.tfvars` + `./infra/deploy.sh demo`. |
| DR-14 | Low | **`collect-evidence.sh` reads scheduler outputs from whatever backend `infra/scheduler` was last initialised with** (`terraform -chdir=infra/scheduler output`). If that was another tenant, evidence queries target the wrong Application Insights. Read-only, so low risk. | Resolve outputs via `./infra/deploy.sh demo output` (which re-inits the demo backend), or run `terraform init -reconfigure -backend-config=infra/tenants/demo.backend.hcl` first. | ✅ Fixed — resolves app/RG via `./infra/deploy.sh demo output` (re-inits demo backend), parses `name = "value"` lines; removed unused `SCHED_DIR`. `bash -n` clean. |

**Also pending (not a defect):** `sub-demo-sandbox` is not created yet (Azure
quota). W10 and scenarios S3 and S9 stay blocked until it exists; re-run
`register-providers.sh` and re-apply `demo/landing-zone` and `demo/workloads`
with `sandbox_subscription_id` set.

---

## 8. Fixes made during the live deploy (DM-31, 2026-10-05)

Four issues surfaced only when deploying to the live demo tenant (they were not
visible to offline `terraform validate` / unit tests). The first three are
**product-code fixes in `infra/`** that affect **every** tenant's deployment, not
just the demo — pushed to `main` in commit `adfdb71`. The fourth is a runtime
app-setting workaround not yet in code. Also recorded in VERIFICATION §6 results
log (2026-10-05). IDs use the **DP-** prefix (deploy fix) to distinguish them
from demo-scaffold review findings (DR-) and live verification issues (V-).

**Status legend:** 🔴 Open · ✅ Fixed (in code) · 🩹 Runtime workaround (not in code)

| ID | Severity | Finding | Fix | Status |
|---|---|---|---|---|
| DP-01 | High | **Storage data-plane 403 (`KeyBasedAuthenticationNotPermitted`)** blocked `terraform plan`/`apply`. The scheduler storage account disables shared keys (SEC-005), but the azurerm provider used shared-key auth to read blob/queue/table properties. Also, the deployer user needs data-plane roles to run Terraform against it. | `infra/scheduler/providers.tf`: add `storage_use_azuread = true`. Operator also needs Storage Blob Data Contributor on the state SA and Blob Data Owner + Queue/Table Data Contributor on the runtime SA. | ✅ Fixed (`adfdb71`) **Follow-up: ✅ Fixed in code + confirmed live (2026-10-05)** — the `function_app` module now grants the deployer (`data.azurerm_client_config.current.object_id`) Storage **Blob Data Owner** + **Queue/Table Data Contributor** on the runtime SA (mirroring the App Configuration Data Owner grant), and the deployment container `depends_on` the deployer blob role to avoid a propagation race. README Prerequisites note + a Troubleshooting row updated. **Re-apply on 2026-10-05 (from a new deployer) created these 3 roles cleanly — 3 added, 0 destroyed, no `409`** (the re-apply trap only bites the *original* deployer, whose manual roles were in neither the state nor this identity). Only the *state* SA role remains a manual pre-Terraform step (Step 2). |
| DP-02 | High | **Function App create fails (BadRequest 51021):** `FUNCTIONS_WORKER_RUNTIME` is invalid as an app setting on Flex Consumption sites. | `infra/modules/function_app/main.tf`: remove the `FUNCTIONS_WORKER_RUNTIME` app setting; the runtime is set via `runtime_name`/`runtime_version`. | ✅ Fixed (`adfdb71`) |
| DP-03 | High | **Cycle-health alert (H2) fails to create:** `Query could not be parsed at ')'`. The measure column was named `cycles`, a **reserved KQL keyword**, so `summarize cycles = count()` was rejected. (The 3 sibling alerts used non-reserved names and deployed fine.) | `infra/modules/monitoring/main.tf`: rename `cycles` → `cycleCount` (column + `metric_measure_column`). | ✅ Fixed (`adfdb71`) |
| DP-04 | High | **Function host drains with storage auth 403s after deploy.** The platform/provider auto-injected a key-based `AzureWebJobsStorage` connection string (empty key, shared keys disabled) that **overrode** the module's identity-based `AzureWebJobsStorage__*` settings (M4), so the host couldn't acquire the timer lease and reported unhealthy. | **Module-level fix (2026-10-05):** `infra/modules/function_app/main.tf` now pins the bare `AzureWebJobsStorage` app setting to `""`, so Terraform owns the key and asserts the empty value on every apply — the provider's key-based re-injection (azurerm #29149) can no longer override the identity-based `__*` settings. Replaces the one-off `az` runtime workaround. | ✅ Fixed in code + **confirmed live (2026-10-05 re-apply)**: the empty-`AzureWebJobsStorage` pin held. Post-apply host settings show `AzureWebJobsStorage__accountName`/`__credential=managedidentity`/`__clientId` set and the bare `AzureWebJobsStorage` **empty** (no key-based re-injection); VERIFICATION §3.4 Query 4 returned **no host storage auth errors** and the timer fired ~1/15 min (Query 3). The host-storage checkpoint in VERIFICATION §3.2 passed. |
| DP-05 | Medium | **Every scheduler plan shows "1 to change" on the Function App.** `APPLICATIONINSIGHTS_CONNECTION_STRING` is set twice in `infra/modules/function_app/main.tf`: in `app_settings` and in `site_config.application_insights_connection_string`. This breaks IAC-008 and the VERIFICATION §4 go-live checkpoint ("the plan's only change is `pwrsched:dryRun`"). | Removed the duplicate from `app_settings`; kept the `site_config` setting (Azure echoes it into `app_settings`, so having both made Terraform see a perpetual diff). | ✅ Fixed (2026-10-05) — added `lifecycle { ignore_changes = [app_settings["AzureWebJobsStorage"]] }` to `azurerm_function_app_flex_consumption.this`. The empty-string pin still sets the value at creation (DP-04), but post-create drift on that one key is ignored, so the perpetual `AzureWebJobsStorage → null` diff is gone. **Confirmed live: `./infra/deploy.sh demo plan` → "No changes. Your infrastructure matches the configuration."** so the strict VERIFICATION §4 go-live checkpoint can now pass. Safety net against a re-injected *key-based* value is the §3.2 host-storage checkpoint (run after every apply/publish); host settings re-verified — `__accountName`/`__credential=managedidentity`/`__clientId` set, bare `AzureWebJobsStorage` empty. (Earlier removal of the duplicate `APPLICATIONINSIGHTS_CONNECTION_STRING` from `app_settings` also stands.) **Correction (2026-10-06):** a fresh `./infra/deploy.sh demo plan` showed the `AzureWebJobsStorage` diff is indeed gone, but a *residual* `0/1/0` remained — Azure injects a `hidden-link: /app-insights-resource-id` tag (from `site_config.application_insights_connection_string`) that is not in `var.tags`, so Terraform wanted to strip it every plan. Added `tags["hidden-link: /app-insights-resource-id"]` to the same `ignore_changes` list; re-plan now genuinely reports **"No changes."** fmt/validate clean. The §4 checkpoint can now pass. |
| DP-06 | Medium | **Deployer role assignments follow whoever runs Terraform.** `deployer_object_id` comes from `data.azurerm_client_config.current` (as the existing App Configuration Data Owner grant does). If a different person or a CI identity runs `plan`, Terraform **replaces** the deployer role assignments: the plan shows changes (breaking the VERIFICATION §4 go-live checkpoint) and the previous deployer loses data-plane access. | Short term: run the go-live `plan`/`apply` as the identity that deployed. Longer term: add a variable for an Entra **group** of operators (default: current identity) and assign the deployer roles (storage + App Configuration) to that group. | 🔴 Open — design concern stands. **Observed on the 2026-10-05 re-apply:** a *different* deployer (new laptop, identity `5de0601a…`) ran `apply`; because the original deployer's role assignments were not in the remote state, Terraform simply **added** this deployer's 3 roles (3 added, 0 destroyed) — no churn this time. But the general risk remains: if the original deployer's assignments *were* in state, a new deployer's plan would replace them. Short term: run go-live `plan`/`apply` as one consistent identity. Longer term: assign the deployer roles (storage + App Configuration) to an Entra **operators group** via a variable (default: current identity). |

> **Note:** DP-05 was first recorded as a benign plan diff, then tracked as an
> issue because it breaks the go-live checkpoint (VERIFICATION §4). The duplicate
> `APPLICATIONINSIGHTS_CONNECTION_STRING` was removed from `app_settings`, but the
> **2026-10-05 re-apply showed the plan is still not clean**: a separate perpetual
> `AzureWebJobsStorage → null` diff remains (azurerm #29149, from the DP-04 pin).
> DP-05 is therefore only **partially fixed** and still blocks the strict §4
> checkpoint — see the DP-05 row for the two closure options.

> **Follow-up:** DP-01, DP-02, DP-03 and DP-04 are fixed in code **and confirmed
> live** on the 2026-10-05 re-apply (deployer roles created cleanly; host uses the
> identity-based storage connection; no host storage auth errors). DP-05 is
> partially fixed (duplicate conn-string gone, but the `AzureWebJobsStorage` diff
> persists). DP-06 stands as a design concern. All code changes were committed to
> `main` and should go through normal code review.

> **Re-apply trap — did NOT bite this time (2026-10-05):** the trap applies only
> to the *original* deployer who manually granted themselves the runtime-storage
> roles. The re-apply was run from a **different** deployer (new laptop) whose
> identity had no such assignments and whose state did not track the original's,
> so Terraform simply **added** the new deployer's 3 roles (3 added, 0 destroyed,
> no `409`). If you later re-apply as the *original* deployer, you must still first
> delete the three manual assignments (Storage Blob Data Owner, Storage Queue Data
> Contributor, Storage Table Data Contributor on the runtime storage account), or
> `terraform import` them into the demo state. Then re-apply in dry run and run
> the DP-04/DP-05 checks above.



---

## Progress log

| Date | Task(s) | Change | Notes |
|---|---|---|---|
| 2026-10-04 | DM-05 | Script authored | `demo/scripts/register-providers.sh`; idempotent, per-subscription, waits for Registered; skips inaccessible subs (handles `sub-demo-sandbox` not existing yet). `bash -n` clean. |
| 2026-10-04 | DM-05 | Ran on 3 subs | All 12 providers reached `Registered` on `sub-demo-management`, `sub-demo-workload-dev`, `sub-demo-workload-prod`. `sub-demo-sandbox` still pending creation (Azure quota) — re-run the script with that sub only once it exists. No credit/offer restrictions hit. |
| 2026-10-04 | — | This tracker created | Decomposed DM-10–DM-44 into offline-now (🟢) vs needs-live-tenant (🔵) subtasks while DM-05 runs. |
| 2026-10-04 | DM-10, DM-11, DM-12, DM-13, DM-14, DM-30 | `demo/landing-zone/` + scheduler tfvars authored (Plan A) | MG hierarchy (§2.2), subscription placement (sandbox count-gated), subscription tags via `azapi_update_resource` (incl. mixed-case `Environment=Prod`, N5), per-subscription budgets 250/500/750, outputs + `render-demo-tfvars.sh`, `demo/scheduler/demo.tfvars.example`. Offline-validated: `terraform fmt` clean, `init -backend=false` OK (azurerm 4.81.0, azapi 2.13.0), `validate` **Success!**; renderer `bash -n` OK. Apply still 🔵 (needs tenant + subs). |
| 2026-10-04 | DM-20, DM-21, DM-22, DM-23 | `demo/workloads/` authored (Plan A default) | W1–W11 core (W2 mixed-case RG `RG-Demo-MixedCase`, W4 opt-out, W7/W8 DBs order=1, W9 prod, W10 sandbox count-gated, W11 platform); W12 AKS / W13 AppGw / W14 SQL MI toggled; `plan_b` single-sub support (DM-22); no public inbound + generated SSH key / DB passwords never output (DM-23). Provider aliases dev/prod/management/sandbox. Offline-validated: `fmt` clean, `init -backend=false` OK, `validate` **Success!** (azurerm 4.x + random + tls). Apply still 🔵. |
| 2026-10-04 | DM-41 | `demo/queries/` authored | Q-A…Q-G (§8) + `verification-3.4-queries.kql` (§3.4 Q1–7). All KQL uses `customDimensions["pwrsched.*"]` matching `telemetry.py` and `monitoring/main.tf`. |
| 2026-10-04 | DM-40, DM-42, DM-43 | `demo/scripts/` authored | 8 scenario scripts + `lib/common.sh`, `collect-evidence.sh`, `teardown.sh`; `demo/.gitignore` (evidence/, tfvars, state). All 11 scripts `bash -n` clean; evidence awk splitter verified (7 statements); §8 comment-strip keeps `let`/inline comments runnable. Effects/runs 🔵. |
| 2026-10-04 | README | `demo/README.md` runbook authored | End-to-end order of operations (prereqs → landing-zone → workloads → scheduler dry-run → Phase A verify → go-live → Phase B scenarios → evidence/demo → teardown), per-step commands cross-checked against built files + `infra/scheduler` outputs (App Config name derived from endpoint since not a scheduler output — no product change), and a scenario→script→query map. Only DM-31 (deploy) and DM-44 (optional workbook) remain. |
| 2026-10-04 | DR-01–DR-11 | Review of demo scaffold `b963585` recorded (§7) | 2 High (wrong var-file paths / unsafe scheduler teardown; SQL MI Azure Hybrid Benefit licence), 3 Medium (Plan B leftovers, Q-G/Q-A count dry-run cycles, public App Gateway listener), 6 Low. V1 product fix `eb0cdd3` reviewed: correct; **149 tests pass / 7 skipped**, ruff clean; live check remains S18. Terraform not validated in the review environment (no binary). |
| 2026-10-04 | DR-01–DR-11 | Review findings fixed | DR-01 (deploy/destroy via `./infra/deploy.sh demo`; added `infra/tenants/demo.{tfvars,backend.hcl}.example`; renderer → `infra/tenants/demo.tfvars`; teardown.sh re-inits demo backend + prints it), DR-02 (SQL MI `LicenseIncluded`), DR-03 (Plan B removed; DM-22 ⚪), DR-04 (`dryRun=="false"` in Q-G/Q-A), DR-05 (appgw NSG), DR-06 (RG profile tag only on W2), DR-08 (dead var removed), DR-09 (Q-C → Q-C1/Q-C2), DR-11 (tag-cleanup step). DR-07 adjusted (MySQL `public_network_access_enabled` is computed in azurerm 4.x — accepted deviation, documented). DR-10 🔍 (README verify + NAT fallback). Validated: `terraform validate` **Success!** (workloads + landing-zone), all 11 scripts `bash -n` clean, evidence splitter still 7, 8 Q-* files. |
| 2026-10-04 | DR-01–DR-14 | Round 2 review of `66bd678` + `4f1f6b9` recorded (§7) | Confirmed fixed: DR-01–DR-06, DR-08, DR-09, DR-11 (DR-10 still verify-live). DR-07 reopened: pinned azurerm 4.81.0 supports `public_network_access = "Disabled"` on MySQL Flexible. New: DR-12 (Medium, `deploy.sh destroy` fails because of `-input=false` without `-auto-approve`), DR-13 (Low, stale `demo/scheduler/demo.tfvars` references), DR-14 (Low, `collect-evidence.sh` reads outputs from the last-initialised backend). Product tests 156 passed, ruff clean; Terraform not validated in the review environment. |
| 2026-10-04 | DR-07, DR-12, DR-13, DR-14, DR-03 | Round-2 findings fixed | DR-07 (MySQL W8 `public_network_access = "Disabled"` — verified settable on pinned azurerm 4.81.0), DR-12 (product `infra/deploy.sh` destroy branch drops `-input=false` so the interactive approval prompt works), DR-13 (DEMO_TENANT_PLAN §2.3 + DM-14 and TASKS DM-14 now reference `infra/tenants/demo.tfvars` + `./infra/deploy.sh demo`), DR-14 (`collect-evidence.sh` resolves outputs via `./infra/deploy.sh demo output`, re-initialising the demo backend; removed unused `SCHED_DIR`), DR-03 leftover (DM-02 note no longer mentions Plan B). Validated: `terraform validate` **Success!** (workloads); `bash -n` clean on `infra/deploy.sh` + `collect-evidence.sh`; DR-14 output parsing simulated OK. |
| 2026-10-05 | DM-01, DM-02, DM-04, DM-10–DM-13 | Landing zone **applied** to demo tenant | Recovered a partial apply by importing 10 MGs + 3 subscription associations into state; converged to **No changes**. Prereqs DM-01/02/04 confirmed satisfied (deploys succeeded). `Environment=Prod` tag on the prod sub verified via `az tag list`. 3 budgets created. Sandbox resources count-gated (absent). |
| 2026-10-05 | DM-06, DM-20, DM-21 | Workloads **applied** (core) | W1–W9, W11 + VMSS W6 + PostgreSQL W7 / MySQL W8 running; `RG-Demo-MixedCase` casing preserved. **Deviation:** `Standard_B1s` capacity-restricted in `southeastasia` *and* `eastasia` (quota was fine, 65 vCPUs); deployed `Standard_B2ts_v2` in **`eastasia`** (updated `demo/workloads/terraform.tfvars`). Also worked around an azurerm "inconsistent result after apply" bug via targeted `terraform import`. W12–W14 off; W10 sandbox 🔵. |
| 2026-10-05 | DM-31 | Scheduler **deployed** + code published; dry-run verified | `./infra/deploy.sh demo apply` → scheduler in `rg-pwrsched-southeastasia` (`func-pwrsched-eorw`, `appcs-pwrsched-eorw`, `appi-pwrsched`, custom role only at `demo-landingzones`+`demo-sandbox`). Code published via `az ... config-zip` (remote build; `func` core tools not installed locally). `reconcile - [timerTrigger]` registered; timer fires every 15 min. Required 4 fixes — see §8 (DP-01–DP-04). |
| 2026-10-05 | DP-01, DP-02, DP-03 | Product-code deploy fixes (pushed to `main` `adfdb71`) | `storage_use_azuread=true` (DP-01), removed `FUNCTIONS_WORKER_RUNTIME` (DP-02), renamed reserved KQL keyword `cycles`→`cycleCount` in cycle-health alert (DP-03). `terraform fmt -check` + `validate` pass. Also committed `infra/scheduler/.terraform.lock.hcl`. These affect any tenant's deploy — flagged for normal code review. |
| 2026-10-05 | DP-04 | Runtime workaround (not in code) | Removed the platform-injected key-based `AzureWebJobsStorage` connection string that overrode the identity-based `__*` settings and drained the host. Terraform does not re-add it; module hardening is a follow-up. |
| 2026-10-05 | T-602 verification | Dry-run checks recorded in VERIFICATION §6 | ✅ C1, H1, N3, N6, §3.3 dry-run checklist; 🟡 M4 (timer+no-auth-errors pass, past-due test pending). Pending: C3 (no SQL MI), H2 (alert tests), N4 (mixed-case fixture), V1 (no AKS). VERIFICATION §0 tracker + results log updated. |
| 2026-10-05 | DP-01, DP-04, DP-05, V2 | Review of live-deploy status recorded | DP-01 and DP-04 follow-ups reopened (deployer runtime-storage roles; DP-04 code fix + post-deploy check). New DP-05 (duplicate App Insights connection string → permanent plan drift, breaks the go-live checkpoint). V2 opened in VERIFICATION §6.1 (one resource `unknown-state-skip` every cycle). Dry-run reading tip added to VERIFICATION §3.3. |
| 2026-10-05 | DP-04, DP-05, DP-01 | Code fixes applied in `infra/` | **DP-04:** `infra/modules/function_app/main.tf` pins bare `AzureWebJobsStorage = ""` (azurerm #29149) so the key-based re-injection can't override the identity-based `__*` settings — replaces the `az` runtime workaround. **DP-05:** removed the duplicate `APPLICATIONINSIGHTS_CONNECTION_STRING` from `app_settings` (kept in `site_config`), fixing the perpetual "1 to change" plan drift (IAC-008 / §4 checkpoint). **DP-01 follow-up:** `function_app` module now grants the deployer Blob Data Owner + Queue/Table Data Contributor on the runtime SA (wired `deployer_object_id` from the root), deployment container `depends_on` the deployer blob role; README Prerequisites note + Troubleshooting row updated. Validated: `terraform fmt -check -recursive infra/` exit 0; `terraform validate` (infra/scheduler) **Success!**. |
| 2026-10-05 | DP-01, DP-04, DP-05, DP-06 | Review of `edf3495` recorded (§8) | Code changes look correct but were validated offline only. DP-04 and DP-05 set to 🔍 verify-after-re-apply (empty `AzureWebJobsStorage` pin unproven; confirm `plan` = No changes and telemetry still flows). New DP-06 (deployer role assignments follow the signed-in identity → plan churn if someone else runs it). Re-apply trap noted: manual deployer roles will collide with the new Terraform assignments (`409 RoleAssignmentExists`) — delete or import first. DP-04 post-deploy checkpoint added to VERIFICATION §3.2. V2 still open. |
| 2026-10-05 | DP-01, DP-04, DP-05, DP-06, V2, M4/N3/H1/N6 | **Re-apply from new laptop + live verification + V2 fix** | Scheduler state is **remote** (`demosatfstate`); re-applied from a second laptop via `./infra/deploy.sh demo` (`init -reconfigure` pulled remote state — the other laptop only held demo landing-zone/workloads *local* state, not needed here). No manual deployer roles existed to delete for this (different) deployer. `apply`: **3 added** (deployer Blob/Queue/Table roles, DP-01) **+ 1 changed** (func app `AzureWebJobsStorage`→null, DP-04) **+ 0 destroyed** — no `409`. **DP-01 ✅ live, DP-04 ✅ live** (host-storage checkpoint pass; §3.4 Q4 empty = no storage auth errors; Q3 timer ~1/15 min). **DP-05 🟡 partial** — re-plan still shows `0/1/0`: a residual `AzureWebJobsStorage → null` diff (azurerm #29149) keeps the strict §4 checkpoint from passing. **DP-06 🔴** no churn this round (new deployer, original roles not in state). §3.4 Queries 1/3/4/6 ✅ (H1/N6/M4/N3). **V2 ✅ fixed + confirmed live**: identified as W6 `vmss-demo-w6`; `src/handlers/vmss.py` now aggregates per-instance power state; 8 unit tests + SDK-surface rows (156 passed/8 skipped, ruff clean); re-published code; 14:00 UTC cycle shows **0 `unknown-state-skip`**. Committed to `main` (`96fb97c`). Also manually deallocated W1/2/3/5/7/8 (user) and **W6** (to position all scheduled dev resources Stopped for the Tue 08:00/08:15/08:30 Bangkok dry-run start-window observation = S1/S12). |
| 2026-10-05 | V2, V3, DP-05, N4 | Review of `96fb97c` + `8eee22f` recorded | V2 fix correct for Uniform; **V3** opened in VERIFICATION §6.1 (Flexible-mode scale sets unsupported; also N+1 API calls per Uniform scale set). DP-05: recommend `ignore_changes` on `app_settings["AzureWebJobsStorage"]` + §3.2 checkpoint. N4: run Query 7 with `RG-Demo-MixedCase` (no new fixture). DP-06 now live: the storage roles belong to the second laptop's identity, so run the go-live plan from there. |
| 2026-10-05 | V3, DP-05 | **V3 fixed + DP-05 closed** | **V3:** `src/handlers/vmss.py` now reads `orchestration_mode` first — Uniform uses `virtual_machine_scale_set_vms.list(expand="instanceView")` (single call, per-instance fallback if not inlined) and aggregates; Flexible raises `HandlerSkip("vmss-flexible-unsupported")`. `src/engine/reconcile.py` `_prefetch_fallback_states` distinguishes `HandlerSkip` from a read failure → logged `skip:<reason>`, `failed==0` (not `state-read-failed`). Added REQUIREMENTS **HR-008**; vmss + reconcile unit tests + `virtual_machine_scale_sets.get` SDK-surface row; **161 passed / 8 skipped**, ruff clean. Live check (a real Flexible scale set) carried forward — none in the demo. **DP-05:** added `lifecycle { ignore_changes = [app_settings["AzureWebJobsStorage"]] }`; `./infra/deploy.sh demo plan` now reports **No changes** — the §4 go-live checkpoint can pass. Host-storage safety net re-verified. `terraform fmt`/`validate` clean. |
| 2026-10-06 | DM-03, DM-05, DM-11, DM-12, DM-13, DM-20, S1/S12, S3, S9, M4/S16, N4, H2/S15, DP-05, DP-06, V3 follow-up | **Sandbox onboarded + full verification day** | **Sandbox:** `sub-demo-sandbox` created (`a8572700-…`), providers registered, placed under `demo-sandbox`, tagged `environment=sandbox`+`schedule-profile=sandbox-default`, 4th budget added, W10 `vm-demo-w10` deployed (eastasia, `Standard_B2ts_v2`). Landing-zone + workloads applied from the stateful laptop; pre-checks run from this laptop (sub state, MG placement, ARG, providers, quota). Demo state split-brain documented → remote-backend scaffolding written (`docs/DEMO_STATE_BACKEND.md`), migration deferred. **Verification (all dry-run, pending reviewer confirmation):** S1/S12 morning start window (08:00 DBs → 08:30 VMs, correct ordering); S3 sub-tag inheritance (W10 `sandbox-default` from the subscription tag); S9 nested-MG exclusion (`excluded-scope` when sub moved into `demo-sandbox-excluded`, returns on restore); M4 past-due (app stopped 05:00→05:20, recovery 05:20:57, cadence resumed 05:30); N4 (W2 `RG-Demo-MixedCase` by Query 7); H2 both alerts fired live (cycle-exceptions 06:32:54, cycle-health 08:45:10); V4 CLI gotcha recorded (§6.2). **Code fixes (pushed to `main`):** DP-05 hidden-link `ignore_changes` (`be3cc45`); DP-06 `var.operator_object_id` (`a5dc27f`/`f043eea`); V3 skip-prefix `skipped:` (`4fafb3f`). DP-05 correction: plan is clean only after the next apply (documented). Tests: 161 passed / 8 skipped, ruff clean. **Remaining:** 17:30 stop window, V1/S18 (W12), C3 (W14), ≥1 business day dry-run, then go-live. |
| 2026-10-06 | S1 (stop), S18/V1, T-603 go-live | **17:30 stop window + AKS + GO-LIVE** | **Stop window:** at 10:30:03 UTC (17:30 BKK) all `weekday-0830-1730` resources' desired state flipped to `Stopped` at the profile boundary (dry-run → `already-converged`); W10 flipped at 18:00 BKK (`sandbox-default`) — completes a full business-day dry-run. **AKS:** provisioned W12 `aks-demo-w12` (node `Standard_B2s_v2`; `Standard_B2s` is `NotAvailableForSubscription` in eastasia) — `terraform apply` 2 added/0 changed/0 destroyed. **S18/V1 (live):** tagged node RG `rg-demo-aks-nodes` `schedule-profile=…`; two cycles (13:45:02, 14:00:02 UTC) logged the node-pool scale set `aks-system-33558043-vmss` as `aks-managed-node-pool`/`action=none` while the cluster was handled by the `aks` handler → **V1 closed**; fixture tag removed. **GO-LIVE (T-603):** set `dry_run=false`; `./infra/deploy.sh demo plan` showed only `pwrsched:dryRun true→false` (0/1/0, strict §4 checkpoint met — DP-04/05 `ignore_changes` held, DP-06 no role churn); applied 14:15 UTC. First live cycle 14:15:04 UTC: `aks-demo-w12 action=stop/result=submitted/dryRun=false`, confirmed `powerState=Stopped` + Activity Log `Stop Managed Cluster` by managed identity `595bf154-…` (SEC-008); W10 `already-converged` (user stopped manually pre-flip); summary `evaluated=11/stopped=1/failed=0`, no `capReached`. SQL MI (W14/C3) kept out of scope. Recorded in VERIFICATION §6; T-602/T-603 tracker rows and V1 closed. |
