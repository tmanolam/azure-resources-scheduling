# Supported Use Cases

| Item | Value |
|---|---|
| Document ID | AZ-PWRSCHED-USECASES-001 |
| Audience | Workload owners, platform team, stakeholders |
| Related | [README.md](../README.md) (how-to steps), [VERIFICATION.md](VERIFICATION.md) (evidence), [REQUIREMENTS.md](REQUIREMENTS.md) (specification) |
| Last updated | 2026-10-07 |
| Evidence basis | Demo tenant: dry run 2026-10-05/06, live since 2026-10-06 21:15 Bangkok, Phase B completed 2026-10-07 (full live business day) |

This page lists what the Resource Power Scheduler does **today**, how to use each
capability, and the evidence that it works. It only claims what has been proven:
each use case shows its current evidence status. Phase B (the first live business
day, [VERIFICATION §4.1](VERIFICATION.md#41-phase-b--live-checks-after-go-live))
completed on 2026-10-07 except two re-runs (S4, S10b), so most scheduling, override,
safety and self-healing use cases are now proven live; UC-10 and UC-18 are 🟢 until
the re-runs pass.

**Status legend**

| Status | Meaning |
|---|---|
| ✅ Proven live | Verified on real resources with `dryRun=false` (or a behaviour that is identical in dry run and live, such as selection and exclusion) |
| 🟢 Proven in part | Proven in dry run, or only partly proven live; the remaining check is listed in the row |
| 🔍 Pending Phase B | Not yet observed; scheduled in VERIFICATION §4.1 |
| ⬜ Not tested | Supported in code and unit-tested, but not verified on Azure |
| ❌ Not supported | Out of scope, or no saving possible |

Scenario IDs (S1, S12, …) refer to [DEMO_TENANT_PLAN §6](DEMO_TENANT_PLAN.md);
check IDs (C1, H2, …) and issue IDs (V1–V5) refer to VERIFICATION.

---

## 1. Use cases

### 1.1 Scheduling

| ID | Use case | How to use it | Evidence | Status |
|---|---|---|---|---|
| UC-01 | **Office-hours schedule.** Resources run 08:30–17:30 Mon–Fri (Bangkok) and are stopped outside those hours. | Tag `schedule-profile=weekday-0830-1730`. See [Onboard resources](../README.md#onboard-resources-workload-owners). | Full live business day (2026-10-07): morning start window (08:00 DBs → 08:15 AKS → 08:30 VMs/VMSS) and the 17:30 stop window (all 8 running resources `stop/submitted`, `failed=0`). | ✅ |
| UC-02 | **Dependency-ordered start.** Databases start first (08:00), then AKS and App Gateway (08:15), then VMs (08:30). Stops run in reverse order. | Automatic by resource type. Override with `schedule-order` (1–9) where needed, e.g. `schedule-order=1` on an AKS cluster that must be ready by 08:30. | S12: live morning start order (2026-10-07) and the live 17:30 reverse-order **stop** (VMs/VMSS order 3 → AKS order 2 → DBs order 1, by submission timestamp). | ✅ |
| UC-03 | **Several schedules side by side.** Each profile has its own windows and time zone. | Use a different profile name, e.g. `sandbox-default` (09:00–18:00). See [Add a new profile](../README.md#add-a-new-profile). | S3: W10 (`sandbox-default`) and dev workloads (`weekday-0830-1730`) evaluated correctly in the same cycles; W10 stopped at 18:00, others at 17:30. | ✅ |
| UC-04 | **Change a schedule without code changes.** | Edit the profile JSON and `terraform apply`. See [Change a schedule](../README.md#change-a-schedule). | NFR-006 by design; profile changes take effect within one cycle. | ⬜ (not exercised in the demo) |

### 1.2 Who is scheduled (scope and tagging)

| ID | Use case | How to use it | Evidence | Status |
|---|---|---|---|---|
| UC-05 | **Tag once at resource-group level.** Every supported resource in the group follows the schedule. | Tag the resource group `schedule-profile=…`. Resource tags override group tags. | S2 / N4: W2 (no own tags) followed its group `RG-Demo-MixedCase`, mixed-case name included. | ✅ |
| UC-06 | **Tag once at subscription level.** Useful for sandboxes. | Tag the subscription `schedule-profile=…`. | S3: W10 (no own tags) followed the subscription tag. | ✅ |
| UC-07 | **Opt one resource out.** | Tag the resource `schedule-enabled=false`. See [Opt out temporarily](../README.md#opt-out-temporarily). | S6: W4 logged `schedule-disabled`, never acted on, every cycle (dry run and live). | ✅ |
| UC-08 | **Choose which management groups are in scope.** | `in_scope_management_group_ids` in Terraform. See [Change scope](../README.md#change-scope-management-group--subscription--resource-group). | The custom role is assigned only at the in-scope groups (R-01 plan check); discovery is limited to them. | ✅ |
| UC-09 | **Exclude a management group, subscription or resource group,** including one nested inside an in-scope group. | `excluded_scope_ids` in Terraform. | S8: Platform VM W11 never appeared. S9: the sandbox subscription moved into a nested excluded group was logged `excluded-scope`, then returned when moved back. | ✅ |

### 1.3 Exceptions and overrides

| ID | Use case | How to use it | Evidence | Status |
|---|---|---|---|---|
| UC-10 | **Work late.** Keep resources running past the stop time. | `schedule-override-state=running` + `schedule-override-until=<time+07:00>` on the resource, group or subscription. See [Ad-hoc start or stop](../README.md#ad-hoc-start-or-stop-override). | S5b (2026-10-07) proved an override `running` starts a stopped resource outside hours, and S5 proved the schedule resumes when an override expires. **Not yet proven:** an override set *before* 17:30 prevents the 17:30 stop (the first S4 run added the override after the stop). S4 re-run pending (VERIFICATION §4.1). | 🟢 |
| UC-11 | **Stop early.** Stop resources during business hours. | `schedule-override-state=stopped` + `schedule-override-until`. | S5 (2026-10-07): W3 override `stopped` → stopped during business hours; started again after the override expired. | ✅ |
| UC-12 | **Ad-hoc start** in the evening or at the weekend. | `schedule-override-state=running` for a period. | S5b (2026-10-07): W1 override `running` in the evening → `action=start, submitted`; stopped again after the override was cleared. | ✅ |

### 1.4 Safety

| ID | Use case | How to use it | Evidence | Status |
|---|---|---|---|---|
| UC-13 | **Production is never touched.** | Tag production subscriptions `environment=prod` (any letter case). No opt-in is possible. | C1 / N5: W9 logged `production-excluded` every cycle, dry run and live, with the mixed-case tag `Environment=Prod`. | ✅ |
| UC-14 | **Platform services are never touched** (hub network, firewall, gateways, Bastion). | Platform management group in `excluded_scope_ids`; firewall, gateway, Bastion and ExpressRoute types are also on a hard-coded deny list. | S8 (above). | ✅ |
| UC-15 | **AKS node pools are never stopped directly.** The cluster is stopped and started through AKS itself. | Automatic. Tag the AKS cluster, never its `MC_` / node resource group. | S18 / V1: the node pool scale set was logged `aks-managed-node-pool` for two cycles while the cluster was scheduled; the cluster was then stopped live. | ✅ |
| UC-16 | **Safety cap.** Limits how many resources one cycle can start or stop, and alerts when reached. | `max_actions_per_run` (default 200). For large estates, size it from the measured peak (REQUIREMENTS §10.1, SC-03). | S14 (2026-10-07): with the cap set to 2, a forced mass transition submitted only 2 actions, logged `capReached=true`, and the OBS-005 cap alert fired. | ✅ |
| UC-17 | **Safe rollout with dry run.** See every decision for a full business day before anything is changed. | `dry_run = true`, then flip to `false`. The go-live plan must change only `pwrsched:dryRun`. | T-602 (full business day) and T-603 (go-live plan showed exactly one change). | ✅ |

### 1.5 Self-healing and resilience

| ID | Use case | How to use it | Evidence | Status |
|---|---|---|---|---|
| UC-18 | **Correct manual changes.** A resource started by hand outside hours is stopped again within one cycle (also covers the 7-day database auto-restart). | Automatic. | S10 (2026-10-07): W7 stopped by hand during business hours was started again in the next cycle (drift corrected live). **Not yet proven:** the outside-hours direction (started by hand or by the 7-day auto-restart → stopped); S10b pending (VERIFICATION §4.1). | 🟢 |
| UC-19 | **VM shut down from inside the OS** (still billed) is deallocated outside hours, or started again inside hours. | Automatic. | S11a (inside hours, 2026-10-07): W5 `StoppedAllocated` → `action=start`. S11b (outside hours, 2026-10-07): W5 `StoppedAllocated` → `action=stop` → `deallocated`. | ✅ |
| UC-20 | **Missed run recovery.** If the scheduler was down, it catches up as soon as it restarts. | Automatic. | M4 / S16: app stopped 20 minutes; the past-due recovery run started 20 seconds after restart and the normal 15-minute cadence resumed. | ✅ |

### 1.6 Monitoring and audit

| ID | Use case | How to use it | Evidence | Status |
|---|---|---|---|---|
| UC-21 | **See what was started or stopped, and why.** | Day-2 workbook (`infra/workbooks/`), or the queries in [Day-2 Operations](../README.md#day-2-operations). Every resource gets a decision record each cycle. | H1 / N3 / N6: every decision carries all fields; one summary per cycle. Workbook in use since 2026-10-06. | ✅ |
| UC-22 | **Get alerted** when cycles stop, fail, repeatedly fail for a resource, or hit the cap. | Four alert rules + action group (`alert_email_addresses`). | H2: cycle-exceptions and cycle-health alerts fired live. S14 (2026-10-07): the cap alert (OBS-005) fired live. The repeated-failure alert (OBS-004) is unit-tested; not observed live (no repeated failures occurred). | ✅ |
| UC-23 | **Audit trail.** Every start/stop is visible in the Azure Activity Log under the scheduler's managed identity. | Activity Log, filtered by the managed identity. | Go-live: `Stop Managed Cluster` with the scheduler identity as caller (SEC-008). | ✅ |

---

## 2. Supported resource types

| Resource type | Handler key | Default order | Dry run | Live stop | Live start | Notes |
|---|---|---|---|---|---|---|
| Virtual machines | `vm` | 3 | ✅ | ✅ (2026-10-07) | ✅ (2026-10-07) | Stopped with **deallocate** (no compute charge). Ephemeral-OS-disk VMs are skipped. Live: W1/W2/W3/W5 started 08:30, deallocated at 17:30. |
| VM scale sets — **Uniform** | `vmss` | 3 | ✅ | ✅ (2026-10-07) | ✅ (2026-10-07, after V5) | Needs the `virtualMachineScaleSets/virtualMachines/read` role action (V5, now in the role). Live: W6 started 08:30, deallocated at 17:30 (V2 running→deallocate). |
| VM scale sets — **Flexible** | `vmss` | — | ⬜ | — | — | **Skipped** as `skipped:vmss-flexible-unsupported`. Tag the member VMs instead (HR-008). |
| AKS clusters | `aks` | 2 | ✅ | ✅ (2026-10-06) | ✅ (2026-10-07) | Node pools are protected (UC-15). Allow 5–10 minutes for start (W12 reached `powerState=Running` ~4.5 min after submit). |
| PostgreSQL Flexible Server | `postgres-flex` | 1 | ✅ | ✅ (2026-10-07) | ✅ (2026-10-07) | Azure auto-starts after 7 days stopped; the scheduler stops it again. Live: W7 start 08:00 and stop 17:30 submitted by the managed identity. |
| MySQL Flexible Server | `mysql-flex` | 1 | ✅ | ✅ (2026-10-07) | ✅ (2026-10-07) | As above (W8). |
| SQL Managed Instance | `sqlmi` | 1 | ⬜ | ⬜ | ⬜ | Supported in code; not deployed in the demo (C3 not tested). |
| Application Gateway | `appgw` | 2 | ⬜ | ⬜ | ⬜ | Supported in code; not deployed in the demo. |

---

## 3. Not supported or limited

| Item | Status | Alternative / plan |
|---|---|---|
| Production workloads | ❌ By design (D-06) | Production is always excluded. Do **not** relabel the subscription's `environment` tag. If production must be scheduled later, see REQUIREMENTS FR-029 (explicit allowlist after a new decision). |
| Public holidays | ❌ Phase 2 (D-07) | Set a `stopped` override for the holiday period. |
| On-demand start/stop API | ❌ Phase 2 (D-05) | Use override tags (UC-10 to UC-12). |
| Azure SQL Database | ❌ Out of scope (D-08) | Use the serverless tier's own auto-pause. |
| App Service / Function Premium "stop" | ❌ No saving (the plan is billed regardless) | Scale the plan down manually. |
| Container Apps, Container Instances | Backlog (REQUIREMENTS §8.3, CH-01–CH-03) | — |
| Cosmos DB, Container Registry, Event Hubs, Service Bus | ❌ No stop operation in Azure | — |
| Flexible scale sets | Limited (skipped) | Tag the member VMs (HR-008). |
| Large tenants (more than about 200–300 transitions in one cycle) | Limited until the scaling backlog lands | Stagger profiles; REQUIREMENTS §10.1 (SC-01–SC-06). |

---

## 4. Operational notes from verification

- **After every `apply` or code publish,** run the host-storage checkpoint
  (VERIFICATION §3.2, DP-04), and confirm `plan` shows **No changes** (DP-05).
- **Run Terraform as one consistent identity,** or set `operator_object_id` to an
  operators group before the first deploy (DP-06).
- **Command-line queries use the Log Analytics workspace** (`AppTraces`); the
  portal, workbook and alerts use Application Insights (`traces`). Both are
  correct (V4).
- **Log retention:** a scheduler-created workspace keeps 30 days; use the
  central workspace for longer history.

---

## Change history

| Date | Change |
|---|---|
| 2026-10-07 | Initial version: 23 use cases with evidence status, resource type matrix, limitations. Phase B items marked 🔍; update them as VERIFICATION §4.1 completes. |
| 2026-10-07 | "Production workloads" row points to REQUIREMENTS FR-029 and warns against relabelling the `environment` tag. |
| 2026-10-07 | **Phase B complete.** Flipped 🔍 → ✅: UC-01 (full live day), UC-02 (live reverse-order stop), UC-10/UC-11/UC-12 (overrides), UC-16 (cap), UC-18/UC-19 (self-heal), UC-22 (cap alert fired). Resource-type matrix: VM/VMSS-Uniform/AKS/PostgreSQL/MySQL live stop and start columns now ✅ (2026-10-07). Evidence in VERIFICATION §6. |
| 2026-10-07 | Review correction: UC-10 and UC-18 set back to 🟢. The first S4 run added the override after the 17:30 stop (proving an ad-hoc restart, not "work late"), and S10 proved drift in the inside-hours direction only. Re-runs S4 and S10b pending in VERIFICATION §4.1. |
