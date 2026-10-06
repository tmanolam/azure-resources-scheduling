# Demo Tenant Plan: Build, Verify and Demonstrate the Power Scheduler

| Item | Value |
|---|---|
| Document ID | AZ-PWRSCHED-DEMO-001 |
| Version | 0.5 |
| Related | [VERIFICATION.md](VERIFICATION.md), [REQUIREMENTS.md](REQUIREMENTS.md), [../README.md](../README.md) |
| Created | 2026-10-04 |
| Audience | Implementer (Kiro), platform team, presenter |
| Budget | Azure credit of USD 1,000 in a fresh tenant |
| Status | In progress — landing zone, workloads, and scheduler deployed; state migrated to remote backend (2026-10-06) |

## 1. Purpose and outcome

Build a small, disposable Azure tenant that mirrors our CAF landing zone, so we can:

1. run the full live verification in [VERIFICATION.md](VERIFICATION.md) (T-602, T-603 and the 8 live checks in §0) without touching a real tenant;
2. exercise every scheduler behaviour with real resources, using **only the existing profiles** (`weekday-0830-1730`, `sandbox-default`) and override tags;
3. demonstrate the solution to stakeholders **from observability logs only**, using evidence collected during verification.

**Done when:** every row in the VERIFICATION §0 tracker is ✅ with evidence in the §6 results log, every scenario in §6 of this plan has passed at least once, and the saved demo queries (§8) show a complete business day.

**Constraints:**
- **No product changes.** No new schedule profiles, no new variables in `infra/` or `src/`. Everything demo-specific lives under `demo/`.
- **Stay within the USD 1,000 credit** with a contingency left over (§4.3).

### ID convention

Tasks in this plan use the prefix **DM-** (`D-` is already used for decisions in REQUIREMENTS.md). Issues found while running the demo use the **V** prefix and go in the VERIFICATION §6 results log. Archived IDs (`T-`, `C1`, `N3`, …) are referenced, never reused.

---

## 2. Target design

### 2.1 Tenant and subscriptions

| Subscription | Purpose | Management group | Subscription tag |
|---|---|---|---|
| `sub-demo-management` | Hosts the scheduler (Function App, App Config, monitoring) and Terraform state | `demo-platform-management` | `environment=platform` |
| `sub-demo-workload-dev` | Main non-production workloads: every handler type and most scenarios | `demo-workload-np` | `environment=dev` |
| `sub-demo-workload-prod` | Production — proves the hard exclusion (C1, N5) | `demo-workload-prod` | `Environment=Prod` (deliberately mixed case, tests N5) |
| `sub-demo-sandbox` | Subscription-level tag inheritance; nested-MG exclusion | `demo-sandbox` | `environment=sandbox`, `schedule-profile=sandbox-default` |

All four subscriptions draw on the USD 1,000 credit.

### 2.2 Management group hierarchy (CAF-lite)

```
Tenant Root Group
└── demo  (intermediate root; role_assignable_scope)
    ├── demo-platform ....................... excluded_scope_ids
    │   ├── demo-platform-management ........ sub-demo-management
    │   └── demo-platform-connectivity ...... (empty; no hub needed)
    ├── demo-landingzones ................... in_scope_management_group_ids
    │   ├── demo-workload-np ................ sub-demo-workload-dev
    │   └── demo-workload-prod .............. sub-demo-workload-prod
    ├── demo-sandbox ........................ in_scope_management_group_ids
    │   └── demo-sandbox-excluded ........... excluded_scope_ids (S9: nested exclude)
    └── demo-decommissioned
```

No hub network or firewall is needed: the scheduler talks to Azure Resource Manager over Microsoft's network, and private networking is disabled in phase 1 (finding H5).

### 2.3 Scheduler configuration for the demo tenant

`infra/tenants/demo.tfvars` (deployed with `./infra/deploy.sh demo`, which uses
`infra/scheduler` exactly as shipped):

| Variable | Demo value | Why |
|---|---|---|
| `role_assignable_scope` | `/providers/Microsoft.Management/managementGroups/demo` | Intermediate root |
| `in_scope_management_group_ids` | `demo-landingzones`, `demo-sandbox` (full IDs) | Resolves OI-01 for the demo tenant |
| `excluded_scope_ids` | `demo-platform`, `demo-sandbox-excluded` (full IDs) | Platform exclusion + nested exclude (S9) |
| `enabled_resource_types` | `["vm","vmss","aks","postgres-flex","mysql-flex","sqlmi","appgw"]` | Trim to match the workload toggles in §4.2 |
| `reconcile_schedule` | `0 */15 * * * *` (default) | Matches production behaviour; needed for the T-602 count checks |
| `dry_run` | `true` first, then `false` | Follows VERIFICATION §3 → §4 |
| `max_actions_per_run` | `200` (temporarily `2` for S14) | Cap test |
| `location` | `southeastasia` | Close to Bangkok, matches the profiles' timezone |

> **Demo vs. target tenant scoping.** In the demo, `demo-workload-prod` stays **inside** the in-scope `demo-landingzones` group on purpose: the scheduler must discover the prod VM to prove the production tag rule (C1, N5) by logging `production-excluded`. Do **not** add it to `excluded_scope_ids` here.
>
> For the **target tenant** (OI-01), use the stricter setup: set `in_scope_management_group_ids` to the non-production workload group only. The custom role is then never assigned above production, so the managed identity has no permissions there; production resources are never discovered; and the tag rule remains as a final safeguard. The trade-off is that the production rule can't be observed in the target tenant, which is why it is proven in the demo.

---

## 3. Prerequisites (manual, before Kiro starts)

| ID | Step | Notes |
|---|---|---|
| DM-01 | **Create the demo tenant** and activate the credit in it | You become Global Administrator. |
| DM-02 | **Confirm what the credit allows** (Cost Management + Billing): which regions and services are allowed, and whether there is a spending limit | A spending limit is useful: if the credit runs out, Azure disables the resources instead of billing you. |
| DM-03 | **Create and rename the subscriptions** per §2.1 | New subscriptions land under Tenant Root until DM-11 moves them. |
| DM-04 | **Elevate access** (Entra ID → Properties → "Access management for Azure resources" = Yes), then sign out and in | Gives the deployer User Access Administrator at Tenant Root, needed for management groups, the custom role and MG-level role assignments. Turn it off again after deployment (§9). |
| DM-05 | **Register resource providers** in each subscription | `Microsoft.Compute`, `Microsoft.Network`, `Microsoft.ContainerService`, `Microsoft.DBforPostgreSQL`, `Microsoft.DBforMySQL`, `Microsoft.Sql`, `Microsoft.Web`, `Microsoft.App`, `Microsoft.AppConfiguration`, `Microsoft.Insights`, `Microsoft.OperationalInsights`, `Microsoft.Storage`. Kiro can script this. |
| DM-06 | **Check vCPU quota** in `southeastasia` | At least 10 B-series vCPUs in the workload subscription. Credit subscriptions sometimes start with low quotas; request increases early. |
| DM-07 | **Check SQL MI options** | Whether the subscription is eligible for Azure's free SQL Managed Instance offer. If it is, use it for W14; if not, W14 runs on the credit for a short window (§4.3). |

---

## 4. Workloads to deploy

### 4.1 Core (always deployed)

All in `southeastasia`. "Standard" means `schedule-profile=weekday-0830-1730`.

| Ref | Resource | Subscription / RG | Own tags | Exercises |
|---|---|---|---|---|
| W1 | Linux VM, `Standard_B1s` | dev / `rg-demo-vm` | Standard | S1 basic schedule |
| W2 | Linux VM, `Standard_B1s` | dev / **`RG-Demo-MixedCase`** (the **RG** is tagged Standard) | none | S2 RG inheritance, N4 |
| W3 | Linux VM, `Standard_B1s` | dev / `rg-demo-override` | Standard | S4/S5 overrides |
| W4 | Linux VM, `Standard_B1s` | dev / `rg-demo-optout` | Standard + `schedule-enabled=false` | S6 opt-out |
| W5 | Linux VM, `Standard_B1s` | dev / `rg-demo-poweroff` | Standard | S11 powered-off VM (H4) |
| W6 | VM scale set, 1 × `Standard_B1s` | dev / `rg-demo-vmss` | Standard | VMSS handler; fallback state read (N7) |
| W7 | PostgreSQL Flexible, Burstable `B1ms` | dev / `rg-demo-db` | Standard + `schedule-order=1` | DB handler, ordering, drift S10 |
| W8 | MySQL Flexible, Burstable `B1ms` | dev / `rg-demo-db` | Standard + `schedule-order=1` | DB handler |
| W9 | Linux VM, `Standard_B1s` | **prod** / `rg-demo-prod` | Standard | S7 production exclusion (C1, N5) |
| W10 | Linux VM, `Standard_B1s` | sandbox / `rg-demo-sandbox` (profile inherited from the **subscription** tag) | none | S3 subscription inheritance |
| W11 | Linux VM, `Standard_B1s` | management / `rg-demo-platform` | Standard | S8 platform exclusion |

VMs need no public IPs, no inbound rules and no SSH access; use a generated SSH key that Terraform does not output. One VNet per subscription, no peering.

W4 (opt-out), W9 (prod) and W11 (platform) are never stopped by the scheduler, so they run 24×7 by design: that is the evidence.

### 4.2 Optional (toggle with Terraform variables; recommended within the credit)

| Ref | Resource | Toggle | Tags | Exercises |
|---|---|---|---|---|
| W12 | AKS, Free tier, 1 system node `Standard_B2s`; set the node resource group name explicitly (e.g. `rg-demo-aks-nodes`) | `enable_aks` | Standard (default order 2) on the **cluster** only | AKS handler, ordering, start guard, S18 (V1) |
| W13 | Application Gateway `Standard_v2`, fixed capacity 1 | `enable_appgw` | Standard (default order 2) | appgw handler |
| W14 | SQL Managed Instance, General Purpose, 4 vCores | `enable_sqlmi` | Standard (default order 1) | sqlmi handler, live check C3 |

If W14 uses the free SQL MI offer, **disable the offer's own built-in start/stop schedule** so only our scheduler controls the instance. If W14 isn't deployed, record C3 as "not tested: no SQL MI in scope" (VERIFICATION §3.4 allows this).

### 4.3 Budget plan for the USD 1,000 credit

Assumes a **4-week** verification and demo period, with scheduled workloads running about 47 hours a week (the standard profile including start offsets) once the scheduler goes live, and 24×7 during the first dry-run week. Figures are rough; confirm in the Azure Pricing Calculator for `southeastasia` before DM-03.

| Item | Estimate for 4 weeks |
|---|---|
| Scheduler (Flex Consumption, App Configuration Standard, App Insights/Log Analytics) | ~USD 50 |
| 8 core VMs + VMSS (3 of them 24×7 by design) + disks | ~USD 50 |
| PostgreSQL + MySQL Burstable B1ms + storage | ~USD 30 |
| AKS (1 × B2s node, load balancer, disks) | ~USD 40 |
| Application Gateway Standard_v2 | ~USD 80–100 |
| SQL MI GP 4 vCore (only if not on the free offer; created for week 3–4) | ~USD 250–350 |
| **Total** | **~USD 250 without SQL MI, ~USD 550–650 with paid SQL MI** |
| Contingency | Remainder of the credit |

Rules to stay within budget:
- **Budget alerts** on the credit subscription(s) at USD 250, 500 and 750 (DM-13).
- **Create W14 last** (after T-602 passes) and destroy it as soon as S17 is recorded.
- **Week 1 runs 24×7 in dry run**, so don't enable W13/W14 until go-live (Phase B).
- If spend tracks above plan, drop W13 first, then W14 (record C3 as not tested).

---

## 5. Implementation tasks for Kiro

All demo code lives under a new top-level `demo/` folder.

```
demo/
├── README.md                     # runbook: order of operations, commands, teardown
├── landing-zone/                 # Terraform: MGs, subscription placement + tags, budgets
├── workloads/                    # Terraform: W1–W14 with toggles
├── scheduler/
│   └── demo.tfvars.example       # §2.3 values for infra/scheduler
├── queries/                      # saved KQL for verification evidence and the demo (§8)
└── scripts/
    ├── scenario-*.sh             # one script per scenario action in §6
    ├── collect-evidence.sh       # runs VERIFICATION §3.4 + demo queries, saves output
    └── teardown.sh
```

### 5.1 Landing zone (Terraform, `demo/landing-zone/`)

| ID | Task | Definition of done |
|---|---|---|
| DM-10 | Management groups per §2.2 | Hierarchy visible in the portal |
| DM-11 | Place subscriptions in MGs (§2.1) | Each subscription under its MG |
| DM-12 | Subscription tags (§2.1), including `Environment=Prod` on prod and `schedule-profile=sandbox-default` on sandbox | `az tag list --resource-id /subscriptions/<id>` shows them. Use `azapi` (`Microsoft.Resources/tags`) or `az tag update`; azurerm has no first-class subscription tag resource. |
| DM-13 | Budgets with email alerts at USD 250 / 500 / 750 on the credit subscription(s) | Visible in Cost Management |
| DM-14 | Outputs: MG and subscription IDs; a script renders `infra/tenants/demo.tfvars` from them | `demo.tfvars` matches §2.3 |

Optional (DM-15): assign an Azure Policy at `demo-workload-prod` that requires the `environment` tag with value `prod` on subscriptions, modelling assumption A-08 for the target tenant.

### 5.2 Workloads (Terraform, `demo/workloads/`)

| ID | Task | Definition of done |
|---|---|---|
| DM-20 | Core workloads W1–W11, exact tags and placement per §4.1 | Resources exist; mixed-case RG name preserved exactly |
| DM-21 | Toggles `enable_aks`, `enable_appgw`, `enable_sqlmi` (default `false`) | Each deploys and destroys independently |
| DM-23 | No public inbound access; SSH key and DB passwords generated, never output | `terraform output` shows no secrets |

### 5.3 Scheduler deployment

| ID | Task | Definition of done |
|---|---|---|
| DM-30 | `demo/scheduler/demo.tfvars.example` with §2.3 values | `./infra/deploy.sh demo plan` shows custom-role assignments only at `demo-landingzones` and `demo-sandbox` |
| DM-31 | Deploy with `dry_run = true`, publish code | VERIFICATION §3.2 checkpoints pass |

### 5.4 Scripts, queries and evidence

| ID | Task | Definition of done |
|---|---|---|
| DM-40 | One script per scenario action in §6: set/clear overrides (resource, RG or subscription), manually start a DB, power off a VM from inside the OS (`az vm run-command invoke … sudo poweroff`), toggle `max_actions_per_run`, break/restore `APP_CONFIG_ENDPOINT`, stop/start the Function App, move the sandbox subscription between MGs | Each script is idempotent and prints what it changed |
| DM-41 | `demo/queries/*.kql`: the demo queries in §8, using the field names from `src/engine/telemetry.py` (`customDimensions["pwrsched.*"]`) | Each query returns data in the demo tenant |
| DM-42 | `collect-evidence.sh <label>` runs VERIFICATION §3.4 Queries 1–7 and the §8 queries, saving output to `demo/evidence/<date>-<label>/` (git-ignored) | Output usable as evidence links in the VERIFICATION §6 results log |
| DM-43 | `teardown.sh` per §9 | Leaves no billable resources; asks for confirmation before destroying |

Optional (DM-44): an Azure Workbook in `demo/` (not in `infra/`) that pins the §8 queries, for a cleaner demo screen.

---

## 6. Test scenarios (existing profiles only)

All times are **Bangkok time** (UTC+7). With the standard profile, transitions happen on weekdays at **08:00** (databases, SQL MI), **08:15** (AKS, App Gateway), **08:30** (VMs) and **17:30** (everything, in reverse order). The sandbox profile runs 08:30 / 08:45 / 09:00 → 18:00. For anything outside those moments, use **override tags**, which act within one cycle (≤ 15 minutes).

### Phase A — dry run (`dry_run = true`), at least one full weekday — covers T-602

| ID | Scenario | When / steps | Expected result | Live check |
|---|---|---|---|---|
| S1 | Daily schedule | Watch 07:45–08:45 and 17:15–17:45 on a weekday | `action=start` decisions at 08:00 (W7, W8), 08:15 (W12, W13), 08:30 (VMs); `action=stop` at 17:30; all `dryRun=true`; nothing in the Activity Log | H1, N6 |
| S2 | RG inheritance, mixed-case RG | Any cycle | W2 decisions show `profile=weekday-0830-1730` | N4 |
| S3 | Subscription inheritance | Any cycle | W10 decisions show `profile=sandbox-default` | — |
| S6 | Opt-out | Any cycle | W4 never gets a start/stop decision | — |
| S7 | Production exclusion | Any cycle | W9 `result=production-excluded` every cycle | C1, N5 |
| S8 | Platform exclusion | Any cycle | W11 never appears in decision records | — |
| S9 | Nested MG exclusion | Move `sub-demo-sandbox` into `demo-sandbox-excluded`; after 2–3 cycles move it back | W10 disappears while excluded, returns after. MG moves can take several minutes to reach Resource Graph | — |
| S13 | Telemetry health | Leave running ≥ 3 hours | Invocations ≈ summaries (Queries 3, 6); no storage errors (Query 4) | M4, N3 |
| S15 | Alerts | VERIFICATION §5 tests (outside business hours is fine) | Cycle-health and cycle-exceptions alerts fire and notify | H2 |
| S16 | Past-due recovery | VERIFICATION §3.4 stop/start test | Past-due run logged after restart | M4 |
| S18 | AKS node pool protection | Requires W12. First check whether AKS copied the cluster's tags onto the node pool scale set in `rg-demo-aks-nodes`. Then tag `rg-demo-aks-nodes` itself `schedule-profile=weekday-0830-1730` and watch 2 cycles; remove the tag afterwards | **Before the V1 fix:** node pool scale sets appear with `action=start/stop` (reproduces V1 safely, because this is dry run). **After the fix:** they appear with `result=aks-managed-node-pool` and no action; the cluster itself is still handled by the `aks` handler | V1 |

### Phase B — live (`dry_run = false`) — covers T-603

Enable W13 and W14 (if budgeted) at the start of Phase B. **Do not run Phase B with W12 enabled until V1 is fixed and S18 passes**; until then, set `enable_aks = false` for Phase B.

| ID | Scenario | When / steps | Expected result | Live check |
|---|---|---|---|---|
| S1L | Daily schedule, live | Next weekday 07:45–08:45 and 17:15–17:45 | Resources actually start/stop at the times in S1; Activity Log shows the managed identity's operations | — |
| S12 | Dependency ordering | Same window as S1L | Order: databases (08:00) → AKS/App Gateway (08:15) → VMs (08:30); at 17:30 the stop decisions are submitted VMs first, databases last | — |
| S4 | Override: work late | Before 17:30, tag `rg-demo-override` `schedule-override-state=running`, `schedule-override-until=<today 19:00+07:00>` | W3 stays running after 17:30; stopped by the first cycle after 19:00 | — |
| S5 | Override: stop early | During business hours (e.g. 13:00), tag `rg-demo-override` `schedule-override-state=stopped` until 14:00 | W3 stops within one cycle; starts again after 14:00 | — |
| S5b | Override: ad-hoc start | In the evening or at the weekend, tag `rg-demo-vm` `schedule-override-state=running` for 1 hour | W1 starts within one cycle; stopped again after the hour | — |
| S10 | Drift correction | Outside business hours, start W7 (PostgreSQL) manually in the portal | Stopped again within one cycle (also models the 7-day auto-restart) | — |
| S11a | Powered off, not deallocated — inside hours | ~10:00, `sudo poweroff` inside W5 | Decision `actualState=StoppedAllocated`, `action=start` (desired is Running); W5 running again | — |
| S11b | Powered off, not deallocated — outside hours | In the evening, start W5 in the portal and power it off from inside before the next cycle | Decision `actualState=StoppedAllocated`, `action=stop`; W5 ends `deallocated` | — |
| S14 | Action cap | In the evening, set `max_actions_per_run = 2`, then tag the **dev subscription** `schedule-override-state=running` for 1 hour | Only 2 starts per cycle; `pwrsched.capReached` logged; cap alert fires. Afterwards restore `200` and let the override expire | — |
| S17 | SQL MI (if W14) | Included in S1L | `actualState` Running/Stopped, never Unknown; start/stop succeed | C3 |

Record every run in the VERIFICATION §6 results log (date, scenario ID, result, evidence folder from DM-42).

---

## 7. Mapping to the VERIFICATION tracker

| VERIFICATION §0 item | Closed by |
|---|---|
| OI-01 | §2.3 demo values (demo tenant only; each real tenant still needs its own) |
| T-602 | Phase A |
| T-603 | Phase B |
| C1 | S7 |
| C3 | S17 (or "not tested" if W14 is skipped) |
| H1 | S1 (Query 1) |
| H2 | S15 |
| M4 | S13, S16 |
| N3 | S13 |
| N4 | S2 |
| N6 | S1 (Query 1) |
| V1 | S18 (after the code fix) |

---

## 8. Stakeholder demo from logs (~15 minutes)

The demo replays a **completed business day** from Application Insights; nothing is changed live. Run it after Phase B, with at least one full live weekday plus the override scenarios in the log.

Saved queries (DM-41), in presentation order:

| # | Query | Shows | Point to make |
|---|---|---|---|
| Q-A | **Day timeline:** start/stop decisions on one weekday, by 15-minute bin and resource type | 08:00 databases → 08:15 AKS/App Gateway → 08:30 VMs; everything stops at 17:30 | It runs itself, in dependency order |
| Q-B | **Decision detail for one cycle:** resource, profile, desired vs actual, action, result | Every resource evaluated, with the reason | Every decision is explained and auditable |
| Q-C | **Exclusions:** count of `production-excluded` results per day; absence of platform resources | Prod skipped every cycle, never acted on | Production and the hub are untouched |
| Q-D | **Overrides in action:** W3 decisions on the S4 evening (`desiredState=Running` after 17:30, stop after 19:00) | Owners extended hours without a ticket | Teams stay in control |
| Q-E | **Self-healing:** W7 manual start (S10) followed by a stop in the next cycle; W5 `StoppedAllocated` → deallocated (S11b) | Drift is corrected automatically | No surprise bills from forgotten resources |
| Q-F | **Cycle health:** summaries per hour (evaluated, started, stopped, skipped, failed) and the alert history from S14/S15 | Steady 15-minute cycles; alerts that fire when they should | It's observable and safe to operate |
| Q-G | **Hours saved:** per resource, cycles where desired state was `Stopped` × 15 minutes, over the demo period | Estimated running hours avoided | The business case, from real data |

Notes for Kiro:
- Overrides are not logged as a separate field; Q-D identifies them by `desiredState=Running` outside the profile's window (or `Stopped` inside it) for the tagged resource.
- Q-G is an estimate of avoided hours, not a cost figure. Multiply by the VM size's hourly rate in the presentation if you want a currency figure.
- Keep App Insights retention at the default (90 days) or longer so the demo data is still there when you present.

---

## 9. Teardown

1. **Export the evidence** if you want to keep it beyond the tenant: run `collect-evidence.sh final`.
2. Set `dry_run = true` on the scheduler (stops all actions within a cycle).
3. `terraform destroy` in `demo/workloads/` (optional components first: SQL MI, App Gateway, AKS).
4. `terraform destroy` in `infra/scheduler` with `demo.tfvars`.
5. `terraform destroy` in `demo/landing-zone/` (subscriptions return to Tenant Root).
6. Delete the Terraform state storage account (`demosatfstate`) **last** — it
   holds the state for all three roots (`infra/scheduler`, `demo/landing-zone`,
   `demo/workloads`), so remove it only after every `terraform destroy` above
   has completed (see [DEMO_STATE_BACKEND.md](DEMO_STATE_BACKEND.md)).
7. Turn off **elevated access** (DM-04).
8. Cancel the subscriptions when the tenant is no longer needed.

---

## 10. Risks and notes

| Risk | Mitigation |
|---|---|
| Credit runs out before the demo | Budget alerts (DM-13); W13/W14 only in Phase B; drop W14 first if spend tracks high |
| Quota too low for B-series VMs or AKS | DM-06 before deployment; request increases early |
| Transitions only happen at 08:00–08:30 and 17:30 | Plan verification sessions around those times; use overrides for everything else |
| SQL MI provisioning time and cost | Optional; free offer if eligible; create after T-602 and destroy after S17 |
| Mixed-case RG name normalised by tooling | Create it with exact casing in Terraform; confirm in the portal before S2 |
| Elevated access left on | Explicit steps in DM-04 and teardown |
| Demo data expires | Default 90-day retention; export evidence (DM-42) before teardown |
| AKS node pools acted on directly (V1) | Phase A only for W12 until V1 is fixed; S18 verifies the fix; never tag the node resource group outside S18 |

---

## Change history

| Version | Date | Changes |
|---|---|---|
| 0.1 | 2026-10-04 | Initial plan |
| 0.2 | 2026-10-04 | No new profiles or product changes: removed the demo-window profile; scenarios now use the real `weekday-0830-1730` / `sandbox-default` windows plus override tags. Demo is logs-only (§8, saved queries). Budget re-planned for a USD 1,000 credit, with Plan B for single-subscription credit offers. Reconcile schedule kept at the 15-minute default. |
| 0.3 | 2026-10-04 | Management groups and subscriptions renamed to match the target tenant (`demo-workload-np`, `demo-workload-prod`, `sub-demo-workload-*`). Single-subscription fallback (Plan B, DM-22) removed: all four subscriptions use the credit. Added §2.3 note on demo vs. target-tenant scoping and optional DM-15 (prod tag policy). |
| 0.4 | 2026-10-04 | Added S18 (AKS node pool protection, verifies V1), explicit AKS node resource group name for W12, Phase B gate on V1, and a matching risk row. |
| 0.5 | 2026-10-06 | Status updated to in-progress. §9 teardown step 6 clarified: state account holds all three roots after migration to remote backend ([DEMO_STATE_BACKEND.md](DEMO_STATE_BACKEND.md)). |
