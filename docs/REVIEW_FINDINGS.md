# Code Review Findings – Phase 1 Implementation

| Item | Value |
|---|---|
| Document ID | AZ-PWRSCHED-REVIEW-001 |
| Related | [REQUIREMENTS.md](REQUIREMENTS.md) (v0.4), [PHASE1_TASKS.md](PHASE1_TASKS.md), [VERIFICATION.md](VERIFICATION.md) |
| Reviewed commit | Round 1: `f081718` · Round 2: `014300e` (PR #1, fix commit `65b6a1e`) · Round 3: `1007a59` |
| Review date | 2026-10-03 |
| Scope | `src/`, `infra/`, `config/`, `tests/`, `.github/workflows/ci.yml`, docs |
| Overall verdict | **Round 3: all findings are closed at the code level. Proceed to T-602 (dry run).** Of the 29 findings across rounds 1–2, 26 are closed and 3 (H1, M4, N3) are fixed in code but need live verification. Live checks for those, plus the live criteria of C1, C3, H2 and N4, are in [VERIFICATION.md §3.4](VERIFICATION.md#34-live-verification-of-review-findings) and §5. Go-live (T-603) requires those checks to pass. Re-run at `1007a59`: pytest 143 passed with pinned SDKs, strict SDK-surface test passes, ruff clean. |

> **How to use this document:** Each finding has an ID, severity, location, evidence, a recommended fix and acceptance criteria. When a finding is fixed, update its **Status**, fill in **Resolved in** (commit or PR) and add a line to the [Status log](#status-log). Do not delete findings; mark them `Closed` or `Won't fix` with a reason.

**Status legend:** 🔴 Open · 🔍 Needs verification (confirm on a live deployment) · 🟡 In progress · ✅ Closed · ⚪ Won't fix (reason required)

**Severity:** **Critical** = breaks a Must requirement or a safety rule, or makes dry-run results misleading · **High** = feature or alerting does not work, or deployment fails in a supported configuration · **Medium** = correctness or scale risk with a workaround · **Low** = hygiene, consistency, documentation

---

## Summary

| ID | Severity | Title | Requirements affected | Status | Resolved in |
|---|---|---|---|---|---|
| C1 | Critical | Production exclusion never triggers | BR-003, US-07, A-08 | ✅ Closed (verify in T-602) | discovery/selection/RBAC fix · `65b6a1e` (PR #1); fail-safe via N1 · `1007a59` |
| C2 | Critical | Resource group and subscription tags are ignored | FR-013, FR-025, US-06 | ✅ Closed | discovery `resourcecontainers` join · `65b6a1e` (PR #1) |
| C3 | Critical | SQL Managed Instance handler cannot start or stop | §8.1 `sqlmi`, D-04 | ✅ Closed | `azure-mgmt-sql==4.0.0` + surface test · `65b6a1e` (PR #1) |
| H1 | High | Decision data probably does not reach Application Insights | OBS-001, OBS-002, OBS-003–005 | 🔍 Fixed, verify in T-602 | OTel flat attributes + KQL aligned · `65b6a1e` (PR #1) |
| H2 | High | Cycle-health alert can never fire | OBS-003 | ✅ Closed | measure column + Total; +exceptions alert · `65b6a1e` (PR #1) |
| H3 | High | Handler skips are counted as failures and retried | HR-001, HR-004, OBS-004 | ✅ Closed | explicit HandlerSkip → skipped · `65b6a1e` (PR #1) |
| H4 | High | Powered-off (not deallocated) VMs are never deallocated | HR-001, OBJ-01 | ✅ Closed | STOPPED_ALLOCATED state + transitions · `65b6a1e` (PR #1) |
| H5 | High | Private networking option breaks the deployment | SEC-007 | ✅ Closed | validation rejects `true` · `65b6a1e` (PR #1) |
| H6 | High | Fixed resource names will collide globally | NFR-010 | ✅ Closed | `random_string` in global names · `65b6a1e` (PR #1) |
| M1 | Medium | Cycle will exceed the 5-minute timeout at scale | NFR-002, NFR-005 | ✅ Closed (follow-up N7) | Resource Graph power state · `65b6a1e` (PR #1) |
| M2 | Medium | Subscription/RG include scopes and nested MG excludes don't work | FR-010, FR-011 | ✅ Closed | scope split + mg_chain exclude · `65b6a1e` (PR #1) |
| M3 | Medium | Custom 429 back-off is dead code | NFR-005 | ✅ Closed | rely on azure-core retry · `65b6a1e` (PR #1) |
| M4 | Medium | Host storage connection for the timer not explicitly configured | FR-007, NFR-004, SEC-001 | 🔍 Fixed, verify in T-602 | AzureWebJobsStorage identity conn · `65b6a1e` (PR #1) |
| M5 | Medium | `succeeded` is treated as a Running power state | FR-004 | ✅ Closed | removed from Running set (with H4) · `65b6a1e` (PR #1) |
| M6 | Medium | `config/settings.json` is not used by Terraform | IAC-004 | ✅ Closed | deleted; tfvars is sole source · `65b6a1e` (PR #1) |
| M7 | Medium | `deploy.sh apply` fails without a plan and reuses stale plans | IAC-007 | ✅ Closed | apply requires+deletes plan · `65b6a1e` (PR #1) |
| L1 | Low | `azuread` provider declared but unused | IAC-005 | ✅ Closed | removed provider · `65b6a1e` (PR #1) |
| L2 | Low | RBAC module lacks scope validation and `principal_type` | SEC-003, R-01 | ✅ Closed | validation + principal_type · `65b6a1e` (PR #1) |
| L3 | Low | Timer schedule read from environment at import time | FR-001 | ✅ Closed | binding expr; key informational · `65b6a1e` (PR #1) |
| L4 | Low | Default order map duplicated | HR-005 | ✅ Closed | single source in handlers.base · `65b6a1e` (PR #1) |
| L5 | Low | Lint issues; no linter in CI | — | ✅ Closed | ruff clean + CI job + ruff.toml · `65b6a1e` (PR #1) |
| L6 | Low | Task log overstates completion; profiles shared across tenants | — | ✅ Closed | docs updated · `65b6a1e` (PR #1) |

**Round 1 counts:** 3 Critical · 6 High · 7 Medium · 6 Low · **22 total: 20 closed, 2 fixed pending live verification (H1, M4)**

### Round 2 summary (re-review of `014300e`)

| ID | Severity | Title | Related | Status | Resolved in |
|---|---|---|---|---|---|
| N1 | High | Production fail-safe never triggers on real Resource Graph output | C1, BR-003 | ✅ Closed | discovery `subId` join-key fail-safe · `1007a59` |
| N2 | Medium | SDK surface test is skipped in CI | C3 | ✅ Closed | strict `sdk-surface` CI job · `1007a59` |
| N3 | Medium | Telemetry may not be flushed before the invocation ends | H1, OBS-002, OBS-003 | 🔍 Needs verification | `flush_telemetry()` force_flush in `finally` · `1007a59` |
| N4 | Low | Resource group join may be case-sensitive | C2, FR-013 | ✅ Closed | KQL lowercases both RG join keys · `1007a59` |
| N5 | Low | Production tag key matched case-sensitively | BR-003, A-08 | ✅ Closed | case-insensitive `environment` lookup · `1007a59` |
| N6 | Low | Boolean attributes may log as `True`/`False` | H1, OBS-001 | ✅ Closed | `_attrs` emits lowercase bool strings · `1007a59` |
| N7 | Low | `max_parallel_arm_calls` still unused | M1, NFR-005 | ✅ Closed | bounded `ThreadPoolExecutor` prefetch · `1007a59` |

**Round 2 counts:** 1 High · 2 Medium · 4 Low · **7 total: 6 closed, 1 fixed pending live verification (N3)**. N1 and N2 are fixed, so T-603 is unblocked at the code level (live verification still required by T-602/T-603).

---

## Critical

### C1 — Production exclusion never triggers

| | |
|---|---|
| **Severity** | Critical |
| **Status** | ✅ Closed at code level in round 3 (fail-safe fixed by [N1](#n1--production-fail-safe-never-triggers-on-real-resource-graph-output)); live criterion checked in T-602 (VERIFICATION §3.3) |
| **Location** | `src/engine/discovery.py` (`build_kql_query`, `_row_to_record`); `src/engine/selection.py` (BR-003 check); `infra/modules/rbac/main.tf` |
| **Requirements** | BR-003, US-07, A-08 |

**Description.** `select_resources` excludes production by reading `ResourceRecord.subscription_tags["environment"]`. Discovery never populates `subscription_tags` (or `resource_group_tags`): the KQL query projects only the resource's own `tags`. The production check therefore always sees an empty map.

**Evidence.** A Resource Graph row for a VM in a subscription tagged `environment=prod` passes through `discover_resources` → `select_resources` with result `(eligible=True, reason='eligible')`. The unit tests do not catch this because `tests/test_selection.py` constructs `ResourceRecord` objects with `subscription_tags` already filled in.

**Recommended fix.**
- Extend the KQL query to join `resourcecontainers` twice: once for the subscription (`type == 'microsoft.resources/subscriptions'`) and once for the resource group (`type == 'microsoft.resources/subscriptions/resourcegroups'`). Project their `tags` as `subscriptionTags` and `resourceGroupTags`.
- Populate `subscription_tags` and `resource_group_tags` in `_row_to_record`.
- Add `Microsoft.Resources/subscriptions/read` to `base_actions` in the RBAC module, so Resource Graph returns subscription rows to the identity.
- Fail safe: if the subscription row cannot be read (missing tags data), treat the resource as ineligible with reason `subscription-tags-unavailable` rather than eligible.

**Acceptance criteria.**
- [ ] An end-to-end unit test feeds a raw Resource Graph row (with joined subscription tags `environment=prod`) through discovery and selection and gets `production-excluded`.
- [ ] A test covers the fail-safe path (subscription tags unavailable → not eligible).
- [ ] Custom role includes `Microsoft.Resources/subscriptions/read`.
- [ ] Verified in T-602 dry run: a tagged resource in a prod subscription logs `production-excluded`.

---

### C2 — Resource group and subscription tags are ignored

| | |
|---|---|
| **Severity** | Critical |
| **Status** | ✅ Closed |
| **Location** | `src/engine/discovery.py` (`build_kql_query`) |
| **Requirements** | FR-013, FR-025, US-06; README "Onboard resources" and "Ad-hoc start or stop" |

**Description.** The query filters `isnotempty(tags['schedule-profile'])` on the **resource's own** tags. Resources that inherit `schedule-profile` from their resource group or subscription are never returned. Override tags set on a resource group (the README's documented ad-hoc method) are never seen either, because RG tags are not fetched (same root cause as C1).

**Recommended fix.**
- Same `resourcecontainers` join as C1.
- Move the opt-in filter after the merge: in KQL, `coalesce(tags['schedule-profile'], resourceGroupTags['schedule-profile'], subscriptionTags['schedule-profile'])` must be non-empty, or drop the KQL filter and rely on `select_resources` (BR-002).

**Acceptance criteria.**
- [ ] Test: resource with no own tags, RG tagged `schedule-profile=weekday-0830-1730` → eligible with that profile.
- [ ] Test: RG tagged `schedule-override-state=stopped` + future `schedule-override-until` → desired state `Stopped` during the window.
- [ ] Test: tag precedence resource > RG > subscription holds end to end (from raw rows).

---

### C3 — SQL Managed Instance handler cannot start or stop

| | |
|---|---|
| **Severity** | Critical |
| **Status** | ✅ Closed |
| **Location** | `src/requirements.txt` (`azure-mgmt-sql==3.0.1`); `src/handlers/sqlmi.py` |
| **Requirements** | §8.1 `sqlmi` (Must), D-04 |

**Description.** `azure-mgmt-sql` 3.0.1 has no `managed_instances.begin_start` / `begin_stop`. Every SQL MI action raises `AttributeError`, which the engine records as `failed` each cycle.

**Evidence.** With the pinned requirements installed: `hasattr(client.managed_instances, "begin_start") == False`. With `azure-mgmt-sql==4.0.0`: both methods exist.

**Recommended fix.**
- Pin `azure-mgmt-sql==4.0.0` (or later).
- Confirm the `state` attribute on the 4.x `ManagedInstance` model still returns `Ready` / `Stopped` / `Starting` / `Stopping`, and adjust `get_state` if not.
- Add a CI smoke test that installs `requirements.txt` and asserts every handler's SDK client exposes the methods it calls (would also have caught this).

**Acceptance criteria.**
- [ ] `requirements.txt` pins a version with `begin_start` / `begin_stop`.
- [ ] SDK-surface smoke test passes in CI for all 7 handlers.
- [ ] SQL MI state values verified against a real instance in T-602.

---

## High

### H1 — Decision data probably does not reach Application Insights

| | |
|---|---|
| **Severity** | High |
| **Status** | 🔍 Fixed in `65b6a1e`; confirm records and attributes in a live `traces` query during T-602 (see also N3, N6) |
| **Location** | `src/engine/telemetry.py`; README Step 6 query; `docs/VERIFICATION.md`; `infra/modules/monitoring/main.tf` (all three alerts) |
| **Requirements** | OBS-001, OBS-002, OBS-003, OBS-004, OBS-005 |

**Description.** Telemetry is emitted with `logger.info(event, extra={"custom_dimensions": {...}})`. That is an OpenCensus convention. The Azure Functions Python worker forwards the log message text to the host; it is expected to drop `extra` fields, so `customDimensions.event`, `resourceId`, `result` etc. would not exist in the `traces` table. If so, the README query, the verification runbook and all three alerts return nothing. Under OpenTelemetry, a nested dict attribute is also not a valid attribute value, so switching exporters alone would not fix it.

**Verification.** On the first deployed cycle (T-602), run `traces | where message startswith "pwrsched." | take 10` and inspect `customDimensions`. If the fields are missing, the finding is confirmed.

**Recommended fix (choose one).**
- **A (simplest):** log the fields as JSON in the message, e.g. `logger.info("pwrsched.decision %s", json.dumps(dims))`, and update every KQL query to `extend d = parse_json(substring(message, indexof(message, "{")))`.
- **B:** enable OpenTelemetry (`azure-monitor-opentelemetry`, `PYTHON_ENABLE_OPENTELEMETRY=true`), and pass **flat** attributes in `extra` (e.g. `extra={"pwrsched.event": ..., "pwrsched.resourceId": ...}`).

**Acceptance criteria.**
- [ ] Verified in a deployed app: each decision and summary record is queryable with all OBS-001 fields.
- [ ] README Step 6 query, VERIFICATION.md and the three alert queries updated to match and return data.

---

### H2 — Cycle-health alert can never fire

| | |
|---|---|
| **Severity** | High |
| **Status** | ✅ Closed |
| **Location** | `infra/modules/monitoring/main.tf` (`cycle_health`) |
| **Requirements** | OBS-003 |

**Description.** The query ends in `summarize cycles = count()`, which always returns exactly one row (with `cycles = 0` when nothing ran). With `time_aggregation_method = "Count"` and no `metric_measure_column`, the alert counts **rows** (always 1), so `<= 0` is never true. The description also promises "cycle failed", but function exceptions are not queried.

**Recommended fix.**
- Set `metric_measure_column = "cycles"` and `time_aggregation_method = "Total"` (keep `LessThanOrEqual 0`).
- Add a second alert (or condition) on `exceptions | where operation_Name == "reconcile"` > 0.

**Acceptance criteria.**
- [ ] Alert fires in a test where the function is disabled for 45+ minutes (`scheduler_enabled = false`).
- [ ] Alert fires when a cycle throws (e.g. temporarily invalid `APP_CONFIG_ENDPOINT` in a test environment).

---

### H3 — Handler skips are counted as failures and retried

| | |
|---|---|
| **Severity** | High |
| **Status** | ✅ Closed |
| **Location** | `src/engine/reconcile.py` (`_invoke_with_backoff`) |
| **Requirements** | HR-001, HR-004, OBS-004 |

**Description.** Handlers raise `HandlerSkip` for "skip, don't retry" cases (ephemeral-OS-disk VMs, HA/replica rejections, AKS not `Succeeded`). The executor catches it in the generic `except Exception` branch, logs an error and returns failure. Result: `result=failed`, retried every cycle, and the OBS-004 repeated-failure alert fires permanently for these resources.

**Evidence.** A handler whose `stop()` raises `HandlerSkip("vm-ephemeral-os-disk-unsupported")` produces `failed=1, skipped=0, result='failed'`.

**Recommended fix.**
- Catch `HandlerSkip` explicitly before the generic handler; record `result="skipped:<reason>"`, increment `skipped`, log at warning level.
- For "no retry until configuration changes" (HR-004), either accept a skip-and-log every cycle (no alert), or cache the skip reason per resource. Document the chosen behaviour in HR-004.

**Acceptance criteria.**
- [ ] Unit test: `HandlerSkip` → `skipped` count, result `skipped:<reason>`, `failed == 0`.
- [ ] OBS-004 alert query does not match skipped results.

---

### H4 — Powered-off (not deallocated) VMs are never deallocated

| | |
|---|---|
| **Severity** | High |
| **Status** | ✅ Closed |
| **Location** | `src/handlers/vm.py`, `src/handlers/vmss.py`, `src/engine/reconcile.py` (`_normalise_actual`) |
| **Requirements** | HR-001, OBJ-01 |

**Description.** Azure reports a VM shut down from inside the OS as `PowerState/stopped`; it is still billed for compute. `_normalise_actual("stopped")` returns `STOPPED`, so when the desired state is Stopped the engine sees "already converged" and never deallocates it.

**Recommended fix.**
- Have the VM and VMSS handlers return a distinct value for `stopped` (e.g. `stopped-allocated`) and add an `ActualState` (e.g. `STOPPED_ALLOCATED`).
- In `_desired_to_action`: desired Stopped + `STOPPED_ALLOCATED` → STOP (deallocate); desired Running + `STOPPED_ALLOCATED` → START.

**Acceptance criteria.**
- [ ] Unit tests for both transitions above.
- [ ] Decision log shows `actualState=StoppedAllocated` for such VMs.

---

### H5 — Private networking option breaks the deployment

| | |
|---|---|
| **Severity** | High |
| **Status** | ✅ Closed |
| **Location** | `infra/modules/function_app/main.tf`, `infra/modules/app_config/main.tf`, `infra/scheduler/main.tf` |
| **Requirements** | SEC-007 |

**Description.** `enable_private_networking = true` disables public network access on the storage account and the App Configuration store, but no private endpoints or private DNS zone records are created. The Function App cannot reach its storage (it will not start) or App Configuration, and Terraform cannot write App Configuration keys.

**Recommended fix (choose one).**
- Implement private endpoints for storage (blob) and App Configuration, with private DNS zone group links (new variables: `private_endpoint_subnet_id`, `private_dns_zone_ids`), and document the hub DNS dependency.
- Or, for phase 1, add a validation on `enable_private_networking` that rejects `true` with a clear message until private endpoints are implemented.

**Acceptance criteria.**
- [ ] Either a working private deployment is verified, or `terraform plan` with `true` fails with an explanatory validation error.
- [ ] README and SEC-007 describe the actual behaviour.

---

### H6 — Fixed resource names will collide globally

| | |
|---|---|
| **Severity** | High |
| **Status** | ✅ Closed |
| **Location** | `infra/scheduler/main.tf` (`locals`) |
| **Requirements** | NFR-010; README "Multiple Tenants" |

**Description.** With the default empty `name_suffix`, names are `func-pwrsched`, `stpwrsched` and `appcs-pwrsched`. Function App hostnames, storage account names and App Configuration names are **globally unique across all of Azure**, not per tenant. The second tenant's deployment will fail, and the first may fail if the names are already taken.

**Recommended fix.**
- Add a `random_string` (e.g. 4–5 lowercase alphanumerics, stored in state) to the globally unique names, or make `name_suffix` required and validated as unique per tenant.
- Update README examples and outputs accordingly.

**Acceptance criteria.**
- [ ] Two deployments with identical tfvars (other than subscription and tenant) produce different global names.

---

## Medium

### M1 — Cycle will exceed the 5-minute timeout at scale

| | |
|---|---|
| **Severity** | Medium |
| **Status** | ✅ Closed (follow-up [N7](#n7--max_parallel_arm_calls-still-unused)) |
| **Location** | `src/engine/reconcile.py` (`plan_actions`, `execute_actions`); `src/host.json` (`functionTimeout`) |
| **Requirements** | NFR-002, NFR-005 |

**Description.** Actual state is read with one ARM call per resource, sequentially; `ReconcileConfig.max_parallel_arm_calls` is defined but unused. At ~0.3–0.5 s per call, 2,000 resources take 10–17 minutes, exceeding the 5-minute `functionTimeout` and NFR-002.

**Recommended fix.**
- Read power state from Resource Graph in the discovery query: VM `properties.extended.instanceView.powerState.code`, AKS `properties.powerState.code`, PostgreSQL/MySQL Flexible and SQL MI `properties.state`, Application Gateway `properties.operationalState`. Call the ARM API only to confirm state just before acting.
- Use a bounded thread pool (`max_parallel_arm_calls`) for any remaining ARM calls.

**Acceptance criteria.**
- [ ] Test with 2,000 simulated resources completes planning without per-resource ARM reads.
- [ ] `max_parallel_arm_calls` is used, or removed from the config.

---

### M2 — Subscription/RG include scopes and nested MG excludes don't work

| | |
|---|---|
| **Severity** | Medium |
| **Status** | ✅ Closed |
| **Location** | `src/runtime.py` (`_build_resource_graph_query_fn`); `src/engine/selection.py` (`_is_under_excluded_scope`) |
| **Requirements** | FR-010, FR-011 |

**Description.**
- Every include scope's last path segment is passed as a management group name, so a subscription or resource group include scope (allowed by FR-010) is silently treated as a non-existent MG.
- Management group exclude scopes are ignored by selection; they only work if the excluded MG is not inside an included MG. Excluding a child MG of Landing Zones has no effect.

**Recommended fix.**
- Split include scopes by type: MGs → `management_groups`, subscriptions → `subscriptions`; RG scopes → subscription query plus an RG filter.
- Join the subscription's `properties.managementGroupAncestorsChain` from `resourcecontainers` (same join as C1) and exclude resources whose chain contains an excluded MG name.

**Acceptance criteria.**
- [ ] Tests: subscription include scope; RG include scope; child-MG exclude inside an included MG.

---

### M3 — Custom 429 back-off is dead code

| | |
|---|---|
| **Severity** | Medium |
| **Status** | ✅ Closed |
| **Location** | `src/engine/reconcile.py` (`RetryableThrottling`, `_invoke_with_backoff`) |
| **Requirements** | NFR-005 |

**Description.** No handler or transport raises `RetryableThrottling`, so the back-off path never runs in production (it is only exercised by unit tests with fakes). The Azure SDK's default retry policy already retries HTTP 429 honouring `Retry-After`.

**Recommended fix.** Either remove the custom back-off and document reliance on the azure-core retry policy (configure `retry_total` / `retry_backoff_max` on the clients), or translate `HttpResponseError` with status 429 into `RetryableThrottling` in `BaseHandler`.

**Acceptance criteria.**
- [ ] One throttling mechanism remains, and it is documented in NFR-005 notes.

---

### M4 — Host storage connection for the timer not explicitly configured

| | |
|---|---|
| **Severity** | Medium |
| **Status** | 🔍 Fixed in `65b6a1e`; confirm the timer fires and past-due recovery works during T-602 |
| **Location** | `infra/modules/function_app/main.tf` (`app_settings`) |
| **Requirements** | FR-007, NFR-004, SEC-001 |

**Description.** `storage_authentication_type = "UserAssignedIdentity"` configures the Flex **deployment** storage. The Functions host also needs `AzureWebJobsStorage` for the timer lease (singleton) and schedule monitor (`use_monitor=True`). With shared keys disabled, it must be an identity-based connection. It is not set explicitly; whether the provider sets it automatically needs confirming.

**Verification.** After deploy, check app settings for `AzureWebJobsStorage*` and confirm the timer fires and `IsPastDue` recovery works.

**Recommended fix.** Set explicitly: `AzureWebJobsStorage__accountName`, `AzureWebJobsStorage__credential = "managedidentity"`, `AzureWebJobsStorage__clientId = <identity client id>`.

**Acceptance criteria.**
- [ ] Timer fires on schedule in a deployed app; host logs show no storage auth errors.

---

### M5 — `succeeded` is treated as a Running power state

| | |
|---|---|
| **Severity** | Medium |
| **Status** | ✅ Closed |
| **Location** | `src/engine/reconcile.py` (`_normalise_actual`) |
| **Requirements** | FR-004 |

**Description.** `"succeeded"` (and `"ready"`) are in the Running set. `Succeeded` is a provisioning state, not a power state; if any handler ever returns it, a stopped resource would be read as running and a needed start would be skipped. (`Ready` is a valid running state for databases and can stay.)

**Recommended fix.** Remove `"succeeded"`; consider making normalisation per handler instead of one global set.

**Acceptance criteria.**
- [ ] Unit test: `_normalise_actual("Succeeded") == UNKNOWN`.

---

### M6 — `config/settings.json` is not used by Terraform

| | |
|---|---|
| **Severity** | Medium |
| **Status** | ✅ Closed |
| **Location** | `config/settings.json`; `infra/modules/app_config/main.tf` |
| **Requirements** | IAC-004 |

**Description.** All settings keys come from Terraform variables; `settings.json` is never read, and its values already differ from `terraform.tfvars.example` (it enables `appgw`). Two sources of truth invite confusion.

**Recommended fix.** Delete `settings.json` and update IAC-004 and the README layout to say settings come from tfvars; or load it as defaults merged with tfvars overrides.

**Acceptance criteria.**
- [ ] One documented source for each setting; IAC-004 matches the implementation.

---

### M7 — `deploy.sh apply` fails without a plan and reuses stale plans

| | |
|---|---|
| **Severity** | Medium |
| **Status** | ✅ Closed |
| **Location** | `infra/deploy.sh` (`apply`) |
| **Requirements** | IAC-007 |

**Description.**
- Without a saved plan, it runs `terraform apply -input=false -var-file=...`. With `-input=false` and no `-auto-approve`, Terraform cannot prompt and exits with an error.
- The `<tenant>.tfplan` file is never deleted after apply, so a later `apply` picks up a stale plan (Terraform rejects it as stale).

**Recommended fix.** Require a fresh plan for `apply` (fail with "run plan first" if missing), delete the plan file after a successful apply, and drop `-input=false` from interactive paths.

**Acceptance criteria.**
- [ ] `plan` → `apply` works; a second `apply` without `plan` gives a clear message.

---

## Low

### L1 — `azuread` provider declared but unused

| | |
|---|---|
| **Status** | ✅ Closed |
| **Location** | `infra/scheduler/providers.tf`; REQUIREMENTS IAC-005 |

Remove the provider and update IAC-005, or keep it only when phase 2 (Entra app roles for the on-demand endpoint) needs it.

### L2 — RBAC module lacks scope validation and `principal_type`

| | |
|---|---|
| **Status** | ✅ Closed |
| **Location** | `infra/modules/rbac/main.tf`, `variables.tf` |

- Add a validation on `in_scope_management_group_ids` that rejects the tenant root MG ID and any ID matching a configurable Platform MG list (SEC-003, R-01).
- Set `principal_type = "ServicePrincipal"` on all role assignments for the managed identity (here and in `app_config` / `function_app`) to avoid failures when the identity was just created.

### L3 — Timer schedule read from environment at import time

| | |
|---|---|
| **Status** | ✅ Closed |
| **Location** | `src/function_app.py` |

Use the binding expression `schedule="%RECONCILE_SCHEDULE%"` instead of `os.environ.get(...)` at module load. Also, `pwrsched:reconcileSchedule` in App Configuration is written but never used by the trigger; remove it or document it as informational.

### L4 — Default order map duplicated

| | |
|---|---|
| **Status** | ✅ Closed |
| **Location** | `src/function_app.py` (`_DEFAULT_ORDER`), `src/handlers/base.py` (`DEFAULT_ORDER_BY_HANDLER`) |

Use `DEFAULT_ORDER_BY_HANDLER` in `function_app.py` and delete the copy.

### L5 — Lint issues; no linter in CI

| | |
|---|---|
| **Status** | ✅ Closed |
| **Location** | `src/`, `tests/`, `.github/workflows/ci.yml` |

Ruff reports ~110 findings (unused imports, unused `noqa`, unused variables, root-logger calls). Run `ruff check --fix`, then add a ruff step to CI.

### L6 — Task log overstates completion; profiles shared across tenants

| | |
|---|---|
| **Status** | ✅ Closed |
| **Location** | `docs/PHASE1_TASKS.md`; `config/profiles/`; README "Multiple Tenants" |

- Reopen T-202 (affected by C1/C2), T-302 (C3, H3, H4), T-404 (H5, M4), T-501/T-502 (H1, H2) until the linked findings close. T-502's "0 gaps" was a field-name check only, not a test of the telemetry pipeline.
- `config/profiles/` is shared by every tenant, so tenants cannot have different schedules. Document this, or support per-tenant profile directories.

---

## Round 2 findings (re-review of `014300e`)

Reviewed 2026-10-03 against the fix commit `65b6a1e` (PR #1). Each finding below was reproduced locally unless marked 🔍.

### N1 — Production fail-safe never triggers on real Resource Graph output

| | |
|---|---|
| **Severity** | High |
| **Status** | ✅ Closed |
| **Location** | `src/engine/discovery.py` (`_row_to_record`, `build_kql_query`); `tests/test_discovery.py` |
| **Related** | C1, BR-003, US-07 |

**Description.** `_row_to_record` sets `subscription_seen = ("subscriptionTags" in row) or ("mgChain" in row)`, i.e. it tests whether the **keys exist**. With a `leftouter` join, Resource Graph returns every projected column; when no subscription row matched, `subscriptionTags` and `mgChain` are present with `null` values. The keys therefore always exist, `subscription_container_seen` is always `True`, and the C1 fail-safe can never fire. The unit test for the fail-safe removes the keys entirely, a shape Resource Graph does not return.

The primary production check still works when the subscription row is readable (the role now includes `Microsoft.Resources/subscriptions/read`), but the safety net for BR-003 fails **open**.

**Evidence.** A row with `"subscriptionTags": null, "mgChain": null` (no own subscription tag data) → `subscription_container_seen=True` → selection result `(eligible=True, reason='eligible')`.

**Recommended fix.**
- Project the subscription join key (e.g. `subId`) and set `subscription_seen = row.get("subId") is not None` (or `isnotnull(subId)` in KQL).
- Change the fail-safe test to use `null`-valued keys, and keep one test with the keys absent.

**Acceptance criteria.**
- [x] Row with `subId: null` → `subscription-tags-unavailable`, not eligible.
- [x] Row with `subId` set and `subscriptionTags: {"environment": "prod"}` → `production-excluded`.
- [x] C1 status returned to Closed once this is fixed (code level; live T-602 criterion still stands under C1).

---

### N2 — SDK surface test is skipped in CI

| | |
|---|---|
| **Severity** | Medium |
| **Status** | ✅ Closed |
| **Location** | `.github/workflows/ci.yml` (`sdk-surface` job); `tests/test_sdk_surface.py` |
| **Related** | C3 (acceptance criterion "passes in CI") |

**Description.** The CI test job installs only `pytest` and `tzdata`. `test_sdk_surface.py` skips each check when its SDK package is missing, so in CI all 7 checks are skipped and a bad SDK pin would pass. The test's docstring says CI installs `requirements.txt`; it does not.

**Evidence.** In a fresh environment with only `pytest` and `tzdata`: `7 skipped`. With `src/requirements.txt` installed: all pass.

**Recommended fix.**
- Add a CI job (or step) that installs `src/requirements.txt` and runs `tests/test_sdk_surface.py`.
- In that job, fail on skips (e.g. an environment variable the test reads to turn skips into failures, or `pytest -rs` plus a check that nothing was skipped).

**Acceptance criteria.**
- [x] New `sdk-surface` CI job installs `src/requirements.txt` and runs `test_sdk_surface.py` with `PWRSCHED_SDK_SURFACE_STRICT=1`; strict mode turns a missing-SDK skip into a failure (verified locally: non-strict → 7 skipped, strict without SDKs → 7 failed), so with the deps installed CI shows 7 passed / 0 skipped.
- [x] Temporarily pinning `azure-mgmt-sql==3.0.1` would make the strict job fail (the surface check for `sqlmi` asserts `begin_start`/`begin_stop`, absent on 3.0.1 — same mechanism proven under C3).

---

### N3 — Telemetry may not be flushed before the invocation ends

| | |
|---|---|
| **Severity** | Medium |
| **Status** | 🔍 Fixed in code; confirm in T-602 |
| **Location** | `src/observability.py`; `src/function_app.py` (`reconcile`) |
| **Related** | H1, OBS-002, OBS-003 |

**Description.** The Azure Monitor OpenTelemetry distro exports log records in background batches. If the Flex Consumption instance is scaled in or frozen soon after a cycle, the final batch (including the `pwrsched.summary` record) can be lost. Missing summaries would also trip the cycle-health alert falsely.

Separately, records from the `pwrsched` loggers are also forwarded by the Functions host, so `traces` will hold a second copy without the `pwrsched.*` attributes. All queries filter on `customDimensions["pwrsched.event"]`, so they are unaffected; this is noted for anyone reading raw traces.

**Recommended fix.** At the end of each invocation (in a `finally`), call `force_flush()` on the OpenTelemetry logger provider (e.g. `opentelemetry._logs.get_logger_provider().force_flush(timeout_millis=...)`, guarded so failures never break the cycle).

**Fix applied.** Added `observability.flush_telemetry(timeout_millis=5000)` — a guarded `force_flush` on `opentelemetry._logs.get_logger_provider()` that no-ops when telemetry was never configured and never raises. `function_app.reconcile` calls it in a `finally` block after each cycle. Unit tests (`tests/test_observability.py`) cover the no-op, the force_flush call with the timeout, and error-swallowing.

**Acceptance criteria.**
- [ ] During T-602, every cycle's `pwrsched.summary` record appears in `traces` (count matches the number of invocations over a few hours).

---

### N4 — Resource group join may be case-sensitive

| | |
|---|---|
| **Severity** | Low |
| **Status** | ✅ Closed |
| **Location** | `src/engine/discovery.py` (`build_kql_query`) |
| **Related** | C2, FR-013 |

**Description.** The join lowercases the right side (`rgName = tolower(name)`) but compares it with the Resources table's `resourceGroup` unchanged. If any resource row carries a mixed-case resource group name, its RG tags (profile and overrides) are silently missing for that resource.

**Recommended fix.** Lowercase both sides, e.g. `| extend rgKey = tolower(resourceGroup)` before the join and join on `rgKey`.

**Acceptance criteria.**
- [x] KQL lowercases both join keys (`rgKey = tolower(resourceGroup)` joined on `$left.rgKey == $right.rgName`); `test_build_kql_lowercases_both_sides_of_rg_join` asserts it.
- [ ] During T-602, a resource in a mixed-case RG inherits the RG's `schedule-profile`.

---

### N5 — Production tag key matched case-sensitively

| | |
|---|---|
| **Severity** | Low |
| **Status** | ✅ Closed |
| **Location** | `src/engine/selection.py` (BR-003 check) |
| **Related** | BR-003, A-08 |

**Description.** Azure tag names are case-insensitive, but the check reads `subscription_tags.get("environment")` exactly. A subscription tagged `Environment=prod` would not be excluded. The A-08 policy should enforce the exact key, but this is the most important safety rule and should not depend on it.

**Recommended fix.** Look up the key case-insensitively (normalise subscription tag keys to lower case before the check).

**Acceptance criteria.**
- [x] Tests: `Environment=prod` and `ENVIRONMENT=Prod` → `production-excluded` (`test_production_exclusion_tag_key_case_insensitive`, `test_production_exclusion_tag_key_and_value_mixed_case`). Implemented via `_get_tag_ci`.

---

### N6 — Boolean attributes may log as `True`/`False`

| | |
|---|---|
| **Severity** | Low |
| **Status** | ✅ Closed |
| **Location** | `src/engine/telemetry.py`; README Step 6; `docs/VERIFICATION.md` |
| **Related** | H1, OBS-001 |

**Description.** Python booleans exported as OpenTelemetry attributes may be stored in `customDimensions` as the strings `True`/`False`. The README and VERIFICATION checklists expect `dryRun` to read `true`; any future query comparing `== "true"` would miss.

**Recommended fix.** Check the stored value during T-602. Either emit booleans as lowercase strings in `_attrs`, or document the actual casing and compare with `tolower()` in queries.

**Fix applied.** `_attrs` now converts any `bool` value to its lowercase string (`str(v).lower()` → `"true"`/`"false"`), so `dryRun` and `capReached` land as `true`/`false` in `customDimensions`, matching the existing README Step 6 and VERIFICATION expectations.

**Acceptance criteria.**
- [x] Docs and queries match the emitted casing: booleans are emitted as `true`/`false`; telemetry tests assert `dryRun == "true"`/`"false"` and `capReached == "false"`. (Observing the stored value in T-602 is now a confirmation, not a dependency.)

---

### N7 — `max_parallel_arm_calls` still unused

| | |
|---|---|
| **Severity** | Low |
| **Status** | ✅ Closed |
| **Location** | `src/engine/reconcile.py` (`ReconcileConfig`, `plan_actions`) |
| **Related** | M1, NFR-005 |

**Description.** M1's acceptance criterion was "`max_parallel_arm_calls` is used, or removed". It is kept, with a comment saying it bounds a thread pool, but no thread pool exists; fallback `get_state` calls (e.g. every VM scale set, which has no power state in Resource Graph) still run sequentially.

**Recommended fix.** Either use it (bounded `ThreadPoolExecutor` for fallback reads) or remove the field and the comment.

**Fix applied.** `plan_actions` now prefetches the fallback `get_state` reads (resources without a Resource Graph `power_state`) via `_prefetch_fallback_states`, a bounded `ThreadPoolExecutor` whose worker count is `min(max_parallel_arm_calls, len(targets))`. `run_reconcile` passes `config.max_parallel_arm_calls`. Read failures are isolated per resource and surface as `state-read-failed` decisions.

**Acceptance criteria.**
- [x] The field is used by code covered by tests: `test_fallback_reads_run_concurrently_bounded_by_config` asserts concurrency occurs and never exceeds the configured bound; `test_fallback_read_failure_is_state_read_failed` covers the failure path.

---

## Round 3 (re-review of `1007a59`)

Reviewed 2026-10-04 against `1007a59` ("Fix round-2 review findings N1-N7"). Each round-2 fix was re-checked by reproduction, not only by reading the tests.

| ID | Result | How it was checked |
|---|---|---|
| N1 | ✅ Confirmed | Row with `subId`, `subscriptionTags` and `mgChain` all `null` → `subscription-tags-unavailable`, not eligible |
| N2 | ✅ Confirmed | Strict mode without SDKs: 7 failed (no skips). Strict mode with `src/requirements.txt`: 7 passed |
| N3 | 🔍 Code confirmed | `flush_telemetry()` runs in `finally`, is guarded, and no-ops when unconfigured. Live check: VERIFICATION §3.4, Queries 3 and 6 |
| N4 | ✅ Confirmed | Generated KQL contains `rgKey = tolower(resourceGroup)` and joins on it |
| N5 | ✅ Confirmed | Subscription tagged `Environment=Prod` → `production-excluded` |
| N6 | ✅ Confirmed | `_attrs(dryRun=True)` → `"true"` |
| N7 | ✅ Confirmed | Fallback `get_state` reads run in a `ThreadPoolExecutor` sized by `max_parallel_arm_calls` |

Two documentation gaps found in round 3 were fixed in the same commit as this update:

- **Status inconsistencies in this document.** The status log returned C1 to Closed, but the C1 summary row, the C1 section, the overall verdict and the round 1 counts still showed it as reopened. The "Resolved in" column for N1–N7 had no commit reference. Both corrected.
- **Live checks missing from the T-602 checklist.** `VERIFICATION.md` covered only production exclusion and quiet alerts. Added §3.4 (checks for C3, H1, M4, N3, N4 and N6, with KQL) and H2 alert-firing tests in §5.

### Live verification tracker

Close each item in its own section and the status log once the check passes in T-602.

| Finding | Live check | Where | Status |
|---|---|---|---|
| C1 | Prod subscription resources logged as `production-excluded` | VERIFICATION §3.3 | 🔍 Pending T-602 |
| C3 | SQL MI `actualState` never `Unknown` | VERIFICATION §3.4, Query 2 | 🔍 Pending T-602 |
| H1 | Decision records carry all OBS-001 fields | VERIFICATION §3.4, Query 1 | 🔍 Pending T-602 |
| H2 | Cycle-health and cycle-exceptions alerts fire | VERIFICATION §5 | 🔍 Pending T-602 |
| M4 | Timer fires on schedule; past-due recovery; no storage auth errors | VERIFICATION §3.4, Queries 3–5 | 🔍 Pending T-602 |
| N3 | Summary count matches invocation count | VERIFICATION §3.4, Queries 3 and 6 | 🔍 Pending T-602 |
| N4 | Mixed-case RG profile inheritance | VERIFICATION §3.4, Query 7 | 🔍 Pending T-602 |
| N6 | `dryRun` stored as `true` | VERIFICATION §3.4, Query 1 | 🔍 Pending T-602 |

---

## Status log

| Date | Finding(s) | Change | By |
|---|---|---|---|
| 2026-10-03 | All | Review completed at commit `f081718`; 22 findings opened | Claude |
| 2026-10-03 | C1, C2 | Fixed: `build_kql_query` now joins `resourcecontainers` (RG + subscription), projects `resourceGroupTags`/`subscriptionTags`/`mgChain`, and resolves opt-in post-merge via `coalesce`; `_row_to_record` populates `subscription_tags`/`resource_group_tags`/`subscription_container_seen`; selection adds a `subscription-tags-unavailable` fail-safe; RBAC `base_actions` gains `Microsoft.Resources/subscriptions/read`. Added 8 end-to-end discovery→selection tests (prod exclusion from raw rows, fail-safe, RG/sub inheritance, RG override, precedence). pytest 110 passed/7 skipped; `terraform fmt`/`validate` clean. Code/static criteria met; the "Verified in T-602 dry run" criterion remains for the live deployment. | Kiro |
| 2026-10-03 | C3 | Fixed: pinned `azure-mgmt-sql==4.0.0` (exposes `managed_instances.begin_start`/`begin_stop`); `_normalise_actual` already maps 4.x `Ready`/`Stopped`/`Starting`/`Stopping`. Added `tests/test_sdk_surface.py` (7 handlers); proven to FAIL on 3.0.1 and PASS on 4.0.0 in a throwaway venv. SQL MI state values against a real instance remain for T-602. | Kiro |
| 2026-10-03 | H1 | Fixed: telemetry now emits **flat** `pwrsched.*` OpenTelemetry attributes (not a nested `custom_dimensions` dict); new `src/observability.py` configures `azure-monitor-opentelemetry` once per worker (dep pinned 1.6.4; `APPLICATIONINSIGHTS_CONNECTION_STRING` app setting added). All KQL aligned to `customDimensions["pwrsched.*"]` — monitoring module (3 alerts), README Step 6, VERIFICATION.md. Verified flat attributes land on the log record and the distro imports. Live `traces` query remains for T-602. | Kiro |
| 2026-10-03 | H2 | Fixed: `cycle_health` now uses `metric_measure_column = "cycles"` + `Total` (was Count on rows, could never fire); added a second `cycle_exceptions` alert on `exceptions | where operation_Name == "reconcile"`. `cap_reached`/`repeated_failures` also hardened to aggregate on a measure column. `terraform validate` passes. Live firing remains for T-602. | Kiro |
| 2026-10-03 | H3 | Fixed: `_invoke_with_backoff` returns an `InvokeOutcome`; `HandlerSkip` (matched structurally to avoid an engine→handlers import) is counted as `skipped` with result `skipped:<reason>`, not `failed`, and is not retried. Unit tests assert skipped≠failed and no retry. | Kiro |
| 2026-10-03 | H4, M5 | Fixed: added `ActualState.STOPPED_ALLOCATED`; VM/VMSS handlers report `stopped-allocated` for `PowerState/stopped` (billed) vs `deallocated`; `_desired_to_action` deallocates (Stopped) or starts (Running) from STOPPED_ALLOCATED. Also removed `succeeded` from the Running set (M5: `_normalise_actual("Succeeded")==UNKNOWN`). Unit tests cover both transitions, the deallocated-converged case, and M5. | Kiro |
| 2026-10-03 | H5 | Fixed: added a validation on `enable_private_networking` rejecting `true` with an explanatory message until private endpoints are implemented. Proven offline (local backend override): plan with `true` fails with the H5 message, `false` passes validation. | Kiro |
| 2026-10-03 | H6 | Fixed: added a state-persisted `random_string` (4 lowercase alphanumerics) to the globally unique names (`func-`, `appcs-`, storage `st...`); storage name worst case 22/24 chars. Two tenants with otherwise-identical tfvars now get distinct global names. `terraform validate` passes with the new `random` provider. | Kiro |
| 2026-10-03 | M1 | Fixed: KQL projects a coalesced `powerState` (VM extended instance view / AKS / DB `state` / AppGw `operationalState`); `_row_to_record` populates `power_state`; `plan_actions` uses `_read_actual_state` (Resource-Graph-first, VM/VMSS `stopped`→`stopped-allocated`, falls back to `handler.get_state` only when absent) so planning needs no per-resource ARM read. `max_parallel_arm_calls` retained for the fallback. Tests cover projection, population, RG-first path, and fallback. | Kiro |
| 2026-10-03 | M2 | Fixed: `runtime._classify_scopes` splits include scopes into management groups / subscriptions / RG filters and the query_fn sets `management_groups` + `subscriptions` + an RG `where` clause; `selection._is_under_excluded_scope` now matches MG exclude scopes against the subscription's `mg_chain` (populated from `managementGroupAncestorsChain`), so excluding a child MG inside an included MG works. Tests cover classification and nested-MG exclusion. | Kiro |
| 2026-10-03 | M3 | Fixed: removed the dead `RetryableThrottling` custom back-off (`_invoke_with_backoff` → single-call `_invoke_handler`); HTTP 429 is handled solely by the azure-core retry policy, configured via `retry_total`/`retry_backoff_max` on the ARM clients in `runtime`. NFR-005 note updated; throttle unit tests replaced with a config-shape assertion. | Kiro |
| 2026-10-03 | M4 | Fixed: set `AzureWebJobsStorage__accountName`/`__credential=managedidentity`/`__clientId` and added Storage Queue + Table Data Contributor roles for the identity (timer singleton lease + schedule monitor with shared keys disabled). Live timer-fires check remains for T-602. | Kiro |
| 2026-10-03 | M6 | Fixed: deleted `config/settings.json` (never read; its values had drifted). `var.settings` (from terraform.tfvars) is the single source of truth; updated IAC-004, README layout, and the app_config variable/locals descriptions. | Kiro |
| 2026-10-03 | M7 | Fixed: `deploy.sh apply` now requires a fresh saved plan (errors with "run plan first" if missing), applies it, and deletes it afterwards so a later apply cannot reuse a stale plan. `bash -n` passes. | Kiro |
| 2026-10-03 | L1 | Fixed: removed the unused `azuread` provider from `providers.tf` (noted it returns in phase 2 for the on-demand endpoint); IAC-005 updated. | Kiro |
| 2026-10-03 | L2 | Fixed: RBAC module validates `in_scope_management_group_ids` (rejects the Tenant Root GUID MG and any `platform_management_group_ids`, wired from `excluded_scope_ids`) and sets `principal_type = "ServicePrincipal"` on all identity role assignments (rbac, app_config, function_app). Both validations proven to fire offline. | Kiro |
| 2026-10-03 | L3 | Fixed: timer uses the `schedule="%RECONCILE_SCHEDULE%"` binding expression instead of reading `os.environ` at import; `pwrsched:reconcileSchedule` documented as informational (not consumed by the trigger). | Kiro |
| 2026-10-03 | L4 | Fixed: `function_app.py` imports `DEFAULT_ORDER_BY_HANDLER` from `handlers.base`; the duplicated `_DEFAULT_ORDER` map is gone. | Kiro |
| 2026-10-03 | L5 | Fixed: `ruff check src tests` passes (E/F/W, config in `ruff.toml`); added a **Ruff lint** CI job and documented the local command in VERIFICATION.md. | Kiro |
| 2026-10-03 | L6 | Fixed: documented that `config/profiles/` is shared across tenants (README "Multiple Tenants") with per-tenant dirs as a future enhancement; added a PHASE1_TASKS progress-log entry recording that the review fixes resolve the defects behind T-202/T-302/T-404/T-501/T-502. | Kiro |
| 2026-10-03 | Summary | **21 of 22 findings closed** at the code/static level (pytest 126 passed/7 skipped; ruff clean; `terraform fmt`/`validate` pass). The remaining work is **live-deployment verification** (T-602 dry run, T-603 go-live), which needs Azure access and the real OI-01 scope values. | Kiro |
| 2026-10-03 | All (round 2) | Re-review of `014300e` (fix commit `65b6a1e`, PR #1) with pinned SDKs installed: pytest 133 passed, ruff clean. 19 findings confirmed closed. Added N1–N7. | Claude |
| 2026-10-03 | C1 | Reopened: main fix (resourcecontainers join, `subscriptions/read`) verified; fail-safe defective because null-valued join columns are treated as "seen" — tracked as N1. | Claude |
| 2026-10-03 | H1, M4 | Status changed from Closed to Fixed, pending verification: acceptance criteria require a live deployment (T-602). | Claude |
| 2026-10-03 | M1 | Closed with follow-up N7 (`max_parallel_arm_calls` unused). | Claude |
| 2026-10-03 | Summary | "Resolved in" column updated from "(local)" to `65b6a1e` (PR #1). Housekeeping noted: `Azure-Resource-Power-Scheduler.pptx` sits in the repo root (suggest `docs/`), and its status slide still shows round-1 counts. | Claude |
| 2026-10-04 | N1, N4 | Fixed: `build_kql_query` now normalises the resource's RG name (`rgKey = tolower(resourceGroup)`) and joins the RG container on `$left.rgKey == $right.rgName` (both lowercased, N4); it projects and keeps the subscription join key `subId`, and `_row_to_record` derives `subscription_container_seen = row.get("subId") is not None` so a null (unmatched) `leftouter` subscription row trips the BR-003 fail-safe (N1). Test `_row` helper updated to the real leftouter shape (present-but-null `subId`/`subscriptionTags`/`mgChain`); added an absent-keys fail-safe test and KQL assertions for `subId` projection + lowercased RG join. discovery+selection tests pass (31). | Kiro |
| 2026-10-04 | N5 | Fixed: added `_get_tag_ci` (case-insensitive tag lookup) in `selection.py`; the BR-003 production hard-exclusion now matches the `environment` key case-insensitively. Tests cover `Environment=prod` and `ENVIRONMENT=Prod`. | Kiro |
| 2026-10-04 | N6 | Fixed: `telemetry._attrs` converts `bool` values to lowercase strings (`"true"`/`"false"`), so `dryRun`/`capReached` land in `customDimensions` matching the README/VERIFICATION expectations. Telemetry tests updated to assert the string casing. | Kiro |
| 2026-10-04 | N3 | Fixed in code: added guarded `observability.flush_telemetry()` (`force_flush` on the OTel logger provider, no-op when unconfigured, never raises); `function_app.reconcile` calls it in a `finally` block. 3 unit tests in `tests/test_observability.py`. Remains 🔍 pending the T-602 live `traces` count check. | Kiro |
| 2026-10-04 | N7 | Fixed: `plan_actions` prefetches fallback `get_state` reads via a bounded `ThreadPoolExecutor` (`_prefetch_fallback_states`, workers = `min(max_parallel_arm_calls, targets)`); `run_reconcile` passes `config.max_parallel_arm_calls`; `ReconcileConfig` comment updated. 2 tests (bounded concurrency; per-resource read-failure → `state-read-failed`). | Kiro |
| 2026-10-04 | N2 | Fixed: `test_sdk_surface.py` reads `PWRSCHED_SDK_SURFACE_STRICT`; in strict mode a missing SDK fails instead of skips. Added a dedicated `sdk-surface` CI job that installs `src/requirements.txt` and runs the surface test with the strict flag. Verified locally: non-strict → 7 skipped; strict without SDKs → 7 failed (proving the gate bites). | Kiro |
| 2026-10-04 | C1 | Returned to Closed at the code level: N1 fixed the fail-safe (null-valued `subId` now detected). The live T-602 dry-run criterion still stands. | Kiro |
| 2026-10-04 | Summary (round 2) | 6 of 7 round-2 findings closed at the code/static level; N3 remains 🔍 pending live T-602. Full suite: **pytest 136 passed / 7 skipped** (the 7 are the SDK-surface checks that only run in the strict `sdk-surface` CI job); **ruff clean**; modified `src/` files `py_compile` clean; `ci.yml` valid YAML. N1 and N2 (the T-603 blockers) are fixed. Terraform unaffected (no infra changes this round). | Kiro |
| 2026-10-04 | N1–N7 (round 3) | Re-review of `1007a59`: N1, N2, N4, N5, N6 and N7 confirmed fixed by reproduction; N3 confirmed in code, pending live check. pytest 143 passed with pinned SDKs; strict SDK-surface test passes; ruff clean. | Claude |
| 2026-10-04 | C1 | Summary row, section status, overall verdict and round 1 counts aligned with Kiro's status-log entry (Closed at code level; live T-602 criterion remains). "Resolved in" for N1–N7 now references `1007a59`. | Claude |
| 2026-10-04 | T-602 checklist | Added VERIFICATION §3.4 (live checks for C3, H1, M4, N3, N4, N6) and H2 alert-firing tests in §5; added the live verification tracker above. | Claude |
| 2026-10-04 | Housekeeping | Deck moved to `docs/presentations/` (`9187c66`); round-2 housekeeping note resolved. The status slide still shows round-1 counts. | Claude |
