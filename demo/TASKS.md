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
| DM-01 | Create demo tenant + activate credit | 🔵 | ⬜ | Operator |
| DM-02 | Confirm credit limits (subscriptions, regions, services, spending limit) | 🔵 | ⬜ | Decides Plan A vs Plan B (§2.1) |
| DM-03 | Create + rename subscriptions (§2.1) | 🔵 | 🟡 | 3 of 4 created; `sub-demo-sandbox` pending Azure quota |
| DM-04 | Elevate access (UAA at Tenant Root), re-login | 🔵 | ⬜ | Turn off again after deploy (§9) |
| DM-05 | Register resource providers in each subscription | 🔵 | 🟡 | Script `scripts/register-providers.sh` ran: all 12 providers Registered on the 3 existing subs (management, workload-dev, workload-prod). ⏳ Re-run for `sub-demo-sandbox` once created |
| DM-06 | Check vCPU quota in `southeastasia` (≥10 B-series) | 🔵 | ⬜ | Operator |
| DM-07 | Check SQL MI free-offer eligibility | 🔵 | ⬜ | Decides W14 funding |

---

## Progress summary (Kiro build tasks)

| Group | Tasks | Done | Status |
|---|---|---|---|
| Scripts & prerequisites | DM-05, DM-40, DM-42, DM-43 | 4 / 4 (DM-05 live-partial) | 🟡 |
| Landing zone (Terraform) | DM-10–DM-14 | 5 / 5 code; apply pending tenant | 🟡 |
| Workloads (Terraform) | DM-20–DM-23 | 4 / 4 code; apply pending tenant | 🟡 |
| Scheduler deployment | DM-30–DM-31 | 1 / 2 | 🟡 |
| Queries & evidence | DM-41, DM-44 | 1 / 2 | 🟡 |
| Runbook | demo/README.md | 1 / 1 | ✅ |
| **Total** | | **16 / 18** | 🟡 |

---

## What can proceed in parallel right now (🟢)

All of these are code/docs, validated offline — **no subscription required**:

- `demo/README.md` runbook (order of operations, commands, teardown)
- `demo/landing-zone/` Terraform (DM-10, DM-14 outputs/renderer) — authored and `terraform validate`-able with no apply
- `demo/workloads/` Terraform (DM-20–DM-23) — authored and validatable
- `demo/scheduler/demo.tfvars.example` (DM-30) — static template
- `demo/scripts/*` (DM-40, DM-42, DM-43) — bash, `bash -n` checkable
- `demo/queries/*.kql` (DM-41) — KQL authored against the known telemetry contract

Blocked until the live tenant exists (🔵): DM-11, DM-12, DM-13 apply-time behaviour,
DM-31 deploy, and every scenario run (S1–S17) / verification (T-602, T-603).

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
- **Status:** 🟡 (code ✅ authored + validated; apply 🔵 — sandbox count-gated for later)

### DM-12 — Subscription tags (§2.1)
- **Buildability:** 🔵 Needs subscriptions; code 🟢
- **DoD:** `environment` tags per §2.1 incl. deliberately mixed-case `Environment=Prod`
  (tests N5) and `schedule-profile=sandbox-default` on sandbox. Use `azapi`
  (`Microsoft.Resources/tags`) or `az tag update` (azurerm has no subscription-tag resource).
- **Status:** 🟡 (code ✅ via `azapi_update_resource`, incl. mixed-case `Environment=Prod`; apply 🔵)

### DM-13 — Budgets + email alerts at USD 250/500/750
- **Buildability:** 🔵 Needs the credit subscription(s); code 🟢
- **DoD:** `azurerm_consumption_budget_subscription` with 3 notifications. Visible in Cost Management after apply.
- **Status:** 🟡 (code ✅ for_each over Plan A subs, thresholds 25/50/75% → 250/500/750; apply 🔵)

### DM-14 — Outputs + demo.tfvars renderer
- **Buildability:** 🟢 fully offline
- **DoD:** Outputs expose MG + subscription IDs; a script renders
  `demo/scheduler/demo.tfvars` from them matching §2.3.
- **Status:** ✅ (`outputs.tf` + `render-demo-tfvars.sh`; bash -n OK; run needs a landing-zone apply first)

---

## 2. Workloads — `demo/workloads/` (DM-20–DM-23)

### DM-20 — Core workloads W1–W11 (§4.1)
- **Buildability:** 🟢 Terraform authorable offline; 🔵 apply needs subs + quota (DM-06)
- **DoD:** W1–W11 with exact tags/placement; **mixed-case RG name `RG-Demo-MixedCase`
  preserved exactly** (S2/N4). VMs: `Standard_B1s`, no public IP, no inbound, generated SSH key.
  One VNet per subscription, no peering. `terraform validate` passes.
- **Status:** ✅ (authored + offline-validated; W1-W11 across workloads_vms_dev/db_vmss/vms_other.tf; apply 🔵)

### DM-21 — Optional toggles (§4.2)
- **Buildability:** 🟢 offline
- **DoD:** `enable_aks`, `enable_appgw`, `enable_sqlmi` (default `false`); each deploys/destroys independently.
- **Status:** ✅ (count-gated W12 AKS / W13 AppGw / W14 SQL MI in `workloads_optional.tf`; apply 🔵)

### DM-22 — Plan B single-subscription support (§2.1)
- **Buildability:** 🟢 offline
- **DoD:** Variable to place all non-prod workloads + sandbox scenarios in one subscription
  using resource groups; same scenarios runnable with one credit subscription.
- **Status:** ✅ (`plan_b` var routes management/sandbox aliases to the dev subscription; validated)

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
- **Status:** ⬜

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
