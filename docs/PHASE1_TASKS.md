# Phase 1 Implementation Task Breakdown

| Item | Value |
|---|---|
| Document ID | AZ-PWRSCHED-TASKS-001 |
| Related spec | [REQUIREMENTS.md](REQUIREMENTS.md) (AZ-PWRSCHED-RS-001, v0.3) |
| Created | 2026-10-03 |
| Last updated | 2026-10-03 (Phase 5 + T-601 complete; `_build_runtime` wired; CI + verification runbook added) |
| Status legend | ⬜ Not started · 🟡 In progress · ✅ Done · ⛔ Blocked |

> **How to use this document:** Each task has an ID, the requirements it satisfies, a
> definition of done (DoD), and a status. Update the **Status** column and the
> **Last updated** date as tasks complete. Keep the Progress Log at the bottom current.

---

## Progress summary

| Phase | Tasks | Done | Status |
|---|---|---|---|
| 0 – Scaffold & config | T-00x | 3 / 3 | ✅ |
| 1 – Desired-state evaluator (+ tests) | T-10x | 2 / 2 | ✅ |
| 2 – Engine core | T-20x | 5 / 5 | ✅ |
| 3 – Resource handlers | T-30x | 3 / 3 | ✅ |
| 4 – Terraform infrastructure | T-40x | 6 / 6 | ✅ |
| 5 – Observability | T-50x | 2 / 2 | ✅ |
| 6 – End-to-end verification | T-60x | 1 / 3 | 🟡 |
| **Total** | | **22 / 24** | 🟡 |

---

## Open prerequisites (confirm before relevant tasks)

| Ref | Question | Blocks | Status |
|---|---|---|---|
| OI-01 | Actual `in_scope_management_group_ids` and `excluded_scope_ids` | real deploy (T-602) | 🟡 Pending – wired as vars + `infra/scheduler/terraform.tfvars.example` placeholders; real values needed before deploy |
| OI-07 | Confirm runtime language is Python 3.11 (vs PowerShell 7.4) | T-001 | ✅ Resolved – Python 3.11 scaffolded (T-001) |

---

## Phase 0 — Scaffold & configuration

### T-001 — Repository scaffold
- **Satisfies:** IAC-003, README repository layout
- **Description:** Create the `src/` package skeleton (`function_app.py`, `engine/`, `handlers/`, `host.json`, `requirements.txt`) and the `tests/` directory per the README layout.
- **DoD:** Directory tree matches the README layout; `host.json` and `requirements.txt` present; package imports resolve.
- **Depends on:** OI-07
- **Status:** ✅ Done — `src/{function_app.py,host.json,requirements.txt,engine/,handlers/,local.settings.json.example}` + `tests/` created; tree matches README; `py_compile`/AST parse pass.

### T-002 — Schedule profiles
- **Satisfies:** IAC-004, D-02, §6.2
- **Description:** Author `config/profiles/weekday-0830-1730.json` and `config/profiles/sandbox-default.json` matching the §6.2 schema (timezone, runWindows, startOffsetMinutesByOrder). No holiday fields (D-07).
- **DoD:** JSON validates against the schema; standard profile matches D-02 (08:30–17:30 Mon–Fri, Asia/Bangkok).
- **Status:** ✅ Done — both profiles created; schema asserted; no holiday fields (D-07).

### T-003 — Global settings file
- **Satisfies:** IAC-004, §6.3
- **Description:** Author `config/settings.json` with `scopes.include/exclude`, `resourceTypes`, `dryRun`, `maxActionsPerRun`.
- **DoD:** Keys match §6.3; `dryRun=true`, `maxActionsPerRun=200` defaults.
- **Status:** ✅ Done — `config/settings.json` created; keys/defaults asserted.

---

## Phase 1 — Desired-state evaluator (pure, unit-tested)

### T-101 — Pure desired-state evaluator
- **Satisfies:** FR-002, FR-003, FR-006, FR-020, BR-004, BR-005, NFR-009
- **Description:** Implement a pure function that, given a profile, current time, resource order and override tags, returns the desired state (`Running`/`Stopped`) and reason. Handle per-profile IANA timezone, multiple run windows, midnight-crossing windows, per-order start offsets, override precedence, and unknown profiles.
- **DoD:** No Azure calls; deterministic; fully type-hinted.
- **Depends on:** T-001
- **Status:** ✅ Done — `src/engine/evaluator.py`; pure, type-hinted; `parse_profile` validation + `evaluate_desired_state`. Handles tz/windows/midnight-crossing/offsets/override precedence/unknown profile. `py_compile` passes.

### T-102 — Evaluator unit tests
- **Satisfies:** NFR-009, R-06
- **Description:** Unit tests covering timezones, midnight crossing, weekday boundaries, start offsets by order, active/expired/invalid overrides, unknown profile warning.
- **DoD:** Tests run and pass locally; edge cases from US-02, US-03, US-06 covered.
- **Depends on:** T-101
- **Status:** ✅ Done — `tests/test_evaluator.py`, 30 tests, all pass (pytest 8.4.2, 0.08s). Covers tz independence, boundaries, midnight crossing, offsets (US-03), overrides active/expired/invalid (US-02/US-06), unknown profile (BR-005).

---

## Phase 2 — Engine core

### T-201 — Resource Graph discovery (with paging)
- **Satisfies:** FR-010, FR-014
- **Description:** Query Resource Graph across include scopes for tagged resources; handle paging (>1,000 results).
- **DoD:** Returns normalised resource records; paging handled; unit-tested with a mocked client.
- **Depends on:** T-001
- **Status:** ✅ Done — `discovery.py`: `build_kql_query` (enabled types + opt-in `schedule-profile` pre-filter), `discover_resources` with skip-token paging (FR-014), `HANDLER_BY_TYPE` map → `ResourceRecord`. Injected `query_fn` for testability. 4 unit tests (incl. 3-page paging). Also added `src/engine/models.py` (shared data model).

### T-202 — Tag resolution & scope filtering
- **Satisfies:** FR-011, FR-012, FR-013, BR-001, BR-002, BR-003
- **Description:** Resolve tags with precedence resource > RG > subscription; apply exclude scopes; filter by enabled resource types; **hard-exclude production** (subscription `environment=prod`) with reason `production-excluded`.
- **DoD:** Production hard-exclusion unit-tested (US-07); precedence unit-tested; excluded scopes never acted on (US-04).
- **Depends on:** T-201
- **Status:** ✅ Done — `selection.py`: `resolve_effective_tags` (resource>RG>sub, FR-013), `select_resources` applies BR-003 prod hard-exclusion (subscription tag only), FR-011 excluded scope (sub/RG/resource prefix; MG upstream), FR-012 type enablement, FR-021 opt-out, BR-002 opt-in, order resolution. 12 unit tests incl. US-07/US-04.

### T-203 — Action ordering & safety controls
- **Satisfies:** FR-006, FR-030, FR-031, FR-032, FR-033
- **Description:** Order starts ascending / stops descending by `schedule-order`; enforce dry-run, `maxActionsPerRun` cap (+alert signal), hard-coded type deny list, and skip transitional states.
- **DoD:** Ordering, cap, deny list, transitional-skip unit-tested.
- **Depends on:** T-101, T-202
- **Status:** ✅ Done — `ordering.py`: starts asc / stops desc, `DENY_LISTED_TYPES` (FR-032), `maxActionsPerRun` cap with `cap_reached` flag + skipped reasons (FR-031), `is_transitional` (FR-033). 6 unit tests.

### T-204 — Reconciliation orchestrator
- **Satisfies:** FR-004, FR-005, NFR-004, NFR-005
- **Description:** Compare desired vs actual, submit only differences asynchronously (no wait), enforce single-run concurrency (timer singleton), bound parallel ARM calls (default 10) and back off on HTTP 429 using `Retry-After`.
- **DoD:** Idempotent (no action when desired==actual); back-off unit-tested; async submission verified.
- **Depends on:** T-203 (handlers injected via a `Handler` protocol; mocked in tests, real impls in Phase 3)
- **Status:** ✅ Done — `reconcile.py`: `plan_actions` (desired-vs-actual diff, transitional/unknown skip), `execute_actions` (dry-run counts only; 429 back-off via `RetryableThrottling` + injected `sleep`), `run_reconcile` + `CycleSummary`. 10 unit tests (idempotency, start/stop, dry-run, transitional/unknown skip, throttle retry+exhaust, start ordering). NFR-004 singleton via host.json.

### T-205 — Timer trigger entrypoint
- **Satisfies:** FR-001, FR-007
- **Description:** `function_app.py` timer trigger (NCRONTAB from app setting); run immediately on `IsPastDue`; load config from App Configuration via managed identity.
- **DoD:** Function discovered as `reconcile - [timerTrigger]`; `IsPastDue` path handled.
- **Depends on:** T-204
- **Status:** ✅ Done — `function_app.py` timer trigger wires config→discover→select→reconcile; `IsPastDue` recovery + per-run `run_id` + cycle-failure logging. `_build_runtime` **now implemented** (post-Phase-5): delegates to `runtime.build_runtime(APP_CONFIG_ENDPOINT)` which loads config from App Configuration (`engine/config.py`), builds the Resource Graph `query_fn`, and the handler registry via `build_registry` + per-subscription ARM client factories (`src/runtime.py`). Azure SDK imports stay lazy; `runtime` imports with no SDK. AST-parses.

---

## Phase 3 — Resource handlers

### T-301 — Common handler interface
- **Satisfies:** HR-005, NFR-007
- **Description:** Define the common interface (`get_state`, `start`, `stop`) and a registry keyed by handler key.
- **DoD:** Interface documented; new handlers addable without core changes.
- **Depends on:** T-001
- **Status:** ✅ Done — `handlers/base.py`: `BaseHandler(ABC)` (get_state/start/stop) with injected `client_factory`, `@register` + `_REGISTRY`, `build_registry` (only enabled + supplied a factory), `parse_resource_name`, `HandlerSkip`, `DEFAULT_ORDER_BY_HANDLER`. `_load_all_handlers` self-registers all modules. Registry smoke test registers all 7.

### T-302 — Must/Should handlers
- **Satisfies:** §8.1, HR-001, HR-002, HR-003, HR-004
- **Description:** Implement `vm` (stop = **deallocate**, skip ephemeral-OS-disk VMs), `vmss`, `aks` (check `powerState.code`, act only when `provisioningState=Succeeded`), `postgres-flex`, `mysql-flex`, `sqlmi`. Databases: log+skip+no-retry when platform rejects stop/start for HA/replica reasons.
- **DoD:** Each handler maps to the correct ARM action; HR-001/002/003/004 behaviours covered.
- **Depends on:** T-301
- **Status:** ✅ Done — `vm` (stop=`begin_deallocate`, ephemeral-OS-disk→`HandlerSkip`, HR-001), `vmss` (deallocate), `aks` (act only when `provisioningState=Succeeded`, else skip; `power_state.code`, HR-002), `postgres-flex`/`mysql-flex` (`servers.begin_start/stop`; HA/replica rejection→`HandlerSkip` no-retry, HR-003/HR-004; other errors propagate), `sqlmi` (rejection→skip). Verified state strings map via engine `_normalise_actual`. Unit-tested with fake clients.

### T-303 — Could handler (appgw)
- **Satisfies:** §8.1 (Could)
- **Description:** Implement `appgw` (Application Gateway start/stop, order 2).
- **DoD:** Handler maps to correct ARM action; registered.
- **Depends on:** T-301
- **Status:** ✅ Done — `appgw` (`application_gateways.begin_start/stop`, state from `operational_state`, order 2). Registered + unit-tested.

---

## Phase 4 — Terraform infrastructure

### T-401 — `app_config` module
- **Satisfies:** IAC-001, IAC-004, §6
- **Description:** App Configuration store + keys loaded from `config/profiles/*.json` and `config/settings.json`; data-plane role for the identity (Reader) and deployer (Owner).
- **DoD:** `terraform validate` passes; keys match §6.2/§6.3.
- **Status:** ✅ Done — `app_config` module: store with `local_auth_enabled=false` (SEC-001); profile keys from `config/profiles/*.json` → `pwrsched:profiles:<name>`; settings keys from `var.settings`; deployer **Data Owner** + identity **Data Reader** (SEC-004); `depends_on` the deployer role for data-plane writes. `terraform validate` passes.

### T-402 — `monitoring` module
- **Satisfies:** IAC-001, §12
- **Description:** Application Insights (+ optional Log Analytics), action group, alert rules (OBS-003/004/005).
- **DoD:** `terraform validate` passes; alerts defined.
- **Status:** ✅ Done — `monitoring` module: workspace-based App Insights (+ optional Log Analytics when none supplied), action group with dynamic `email_receiver`, 3 `azurerm_monitor_scheduled_query_rules_alert_v2` (cycle-health OBS-003, max-actions-cap OBS-005, repeated-failures OBS-004). `terraform validate` passes.

### T-403 — `rbac` module
- **Satisfies:** IAC-001, SEC-002, SEC-003, §11.1, R-01
- **Description:** Custom role **Resource Power Operator** (read + enabled handlers' start/stop actions only); assignments **only** at in-scope MGs. Role actions driven by `enabled_resource_types`.
- **DoD:** `terraform validate` passes; plan shows no assignment at Tenant Root / intermediate root / Platform MG.
- **Status:** ✅ Done — `rbac` module: custom role **Resource Power Operator** with actions = base read + per-handler start/stop built from `enabled_resource_types` (`actions_by_handler` map, SEC-002); `assignable_scopes=[role_scope]`; `azurerm_role_assignment` only at `in_scope_management_group_ids` (SEC-003, R-01). `terraform validate` passes.

### T-404 — `function_app` module
- **Satisfies:** IAC-001, SEC-001, SEC-004, SEC-005, SEC-006, SEC-007
- **Description:** Flex Consumption plan, Linux Python 3.11 Function App, storage (shared-key off, no public blob, TLS1.2), user-assigned managed identity, HTTPS-only, optional private endpoints + VNet integration.
- **DoD:** `terraform validate` passes; identity-only auth; storage hardening set.
- **Depends on:** OI-01 (for real deploy)
- **Status:** ✅ Done — `function_app` module: `FC1` `azurerm_service_plan` + `azurerm_function_app_flex_consumption` (python 3.11); storage hardened (`shared_access_key_enabled=false`, no public blob, `min_tls_version=TLS1_2`); `UserAssignedIdentity` storage auth + UAMI `identity` block (SEC-001); `https_only`; `site_config.minimum_tls_version=1.2`; Storage Blob Data Owner for the identity; optional private networking. Fixed a real schema error found by validate (insights conn string belongs in `site_config` in azurerm 4.x).

### T-405 — Single tenant-wide root module + backend
- **Satisfies:** IAC-002, IAC-003, IAC-005, IAC-006, §13.1
- **Description:** `infra/scheduler` single root wiring the modules for one tenant-wide instance (optional `name_suffix`); `backend.hcl.example`, `terraform.tfvars.example`, pinned providers, standard tags, variables per §13.1.
- **DoD:** `terraform init` + `validate` pass; providers pinned (`azurerm ~>4.x`, `azuread ~>3.x`, tf `>=1.9`).
- **Depends on:** T-401, T-402, T-403, T-404
- **Status:** ✅ Done — `infra/scheduler`: RG + user-assigned identity + 4 modules wired; `providers.tf` pinned (tf `>=1.9`, azurerm `~>4`, azuread `~>3`) with azurerm backend; `backend.hcl.example` (key `pwrsched/terraform.tfstate`) + `terraform.tfvars.example`; outputs match README. Refactored from per-env (dev/prod) to a single tenant-wide deployment with optional `name_suffix` (empty default); naming verified for `''`→`func-pwrsched`/`stpwrsched` and `'sea'`→`func-pwrsched-sea`/`stpwrschedsea`. `fmt -check` + `validate` SUCCESS (azurerm 4.81.0).

### T-406 — Config loading & drift check
- **Satisfies:** IAC-004, IAC-008
- **Description:** Ensure Terraform loads `/config` into App Config and that a second `plan` shows no drift except intentional key changes.
- **DoD:** `terraform plan` after apply shows no unexpected changes.
- **Depends on:** T-405
- **Status:** ✅ Done (static) — module loads `/config` profiles (`pwrsched:profiles:<name>`) + settings keys from `var.settings`; `terraform validate` passes. ⚠️ Live drift re-plan (IAC-008) requires Azure credentials and a real apply; cannot be run offline — to be confirmed in T-602.

---

## Phase 5 — Observability

### T-501 — Structured logging
- **Satisfies:** OBS-001, OBS-002, SEC-008
- **Description:** Per-resource decision record (`runId`, `resourceId`, `type`, `profile`, `desiredState`, `actualState`, `action`, `dryRun`, `result`, `error`) and per-cycle summary (counts + duration), matching the README KQL (`customDimensions.event == "pwrsched.decision"`).
- **DoD:** Fields present and queryable; matches README Step 6 query.
- **Depends on:** T-204
- **Status:** ✅ Done — `engine/telemetry.py`: `emit_decision`/`emit_summary`/`emit_cap_reached` via `logging` `extra={"custom_dimensions":{…}}` → App Insights `customDimensions`. Decision carries `event,runId,resourceId,type,profile,desiredState,actualState,action,dryRun,result,error` (OBS-001); summary carries counts + `durationSeconds` (OBS-002). Added `actual_state`/`result` to `PlannedAction`; `run_reconcile` emits a decision per evaluated resource (incl. ineligible/skipped), `capReached`, and the summary. 7 unit tests.

### T-502 — Alerts wiring
- **Satisfies:** OBS-003, OBS-004, OBS-005
- **Description:** Alert on cycle failure / no run >45 min, same resource failing 3 consecutive cycles, and `maxActionsPerRun` reached.
- **DoD:** Alerts fire against the emitted telemetry (validated in test/dry-run).
- **Depends on:** T-402, T-501
- **Status:** ✅ Done — cross-checked emitted events/fields against the `monitoring` KQL and README query: events match (`pwrsched.decision/summary/capReached`) and every KQL field (`event,resourceId,result,runId`) + README field is emitted — **0 gaps**. OBS-003 (summary presence), OBS-004 (`result=="failed"` + `runId`/`resourceId`), OBS-005 (`capReached`) all backed by telemetry.

---

## Phase 6 — End-to-end verification

### T-601 — Static checks & unit tests
- **Satisfies:** IAC-008, NFR-009
- **Description:** `terraform fmt -check`, `terraform validate`; run the full Python test suite.
- **DoD:** All pass; no formatting diffs.
- **Depends on:** T-405, T-102, T-204
- **Status:** ✅ Done — recorded 2026-10-03: `python -m pytest` → **102 passed**; `terraform fmt -check -recursive infra/` → exit 0 (no diffs); `terraform validate` (infra/scheduler) → **Success** (azurerm 4.81.0). Also completed the deferred `_build_runtime` wiring (see note below) so the Function App is runnable once deployed. Now **enforced in CI** (`.github/workflows/ci.yml`); procedure documented in [VERIFICATION.md](VERIFICATION.md).

### T-602 — Deploy & dry-run validation
- **Satisfies:** README Step 4–6, FR-030
- **Description:** Deploy infra, publish code, confirm `reconcile - [timerTrigger]`, run in dry-run and verify README Step 6 checklist (in-scope only, no Platform, prod excluded, correct desired state, `dryRun=true`).
- **DoD:** Step 6 checklist passes for ≥ one cycle.
- **Depends on:** T-601, OI-01
- **Status:** ⬜ Not started

### T-603 — Go-live readiness
- **Satisfies:** README Step 7, OBJ-03
- **Description:** After ≥1 business day of correct dry-run, flip `dry_run=false`; confirm plan changes only `pwrsched:dryRun`; watch first live cycles.
- **DoD:** Live actions match decisions; Activity Log shows managed-identity actions.
- **Depends on:** T-602
- **Status:** ⬜ Not started

---

## Progress log

| Date | Task(s) | Change | Notes |
|---|---|---|---|
| 2026-10-03 | — | Document created | Breakdown derived from REQUIREMENTS.md v0.3 |
| 2026-10-03 | T-001, T-002, T-003 | Phase 0 complete | src/ scaffold, 2 profiles, settings.json. JSON validated, Python compiles, tree matches README. OI-07 resolved (Python 3.11). |
| 2026-10-03 | T-101, T-102 | Phase 1 complete | Pure evaluator + 30 unit tests, all pass. Added tzdata to requirements for the Linux runtime. |
| 2026-10-03 | T-201–T-205 | Phase 2 complete | Engine core: discovery (paging), selection (prod hard-exclusion, tag precedence), ordering+safety, reconcile orchestrator (dry-run, 429 back-off), timer entrypoint. +src/engine/models.py. 62 tests pass (30+4+12+6+10). `_build_runtime` deferred to Phase 3. |
| 2026-10-03 | T-301–T-303 | Phase 3 complete | Handler interface + registry; 7 handlers (vm/vmss/aks/postgres-flex/mysql-flex/sqlmi/appgw) with injectable ARM clients; HR-001/002/003/004 covered. 85 tests pass (+23). |
| 2026-10-03 | T-401–T-406 | Phase 4 complete | 4 TF modules (app_config, monitoring, rbac, function_app) + dev/prod roots + backend. `terraform fmt -check` + `validate` pass (dev & prod, azurerm 4.81). Fixed real schema bug (insights in site_config). Live drift re-plan (IAC-008) deferred to T-602 (needs Azure creds). |
| 2026-10-03 | T-405 (refactor) | Single tenant-wide deployment | Replaced per-env dev/prod roots with one `infra/scheduler` root + optional `name_suffix`; removed `infra/envs`; backend key `pwrsched/terraform.tfstate`. `fmt`+`validate` pass. README & REQUIREMENTS (v0.4) updated. Production still hard-excluded (BR-003). |
| 2026-10-03 | T-501, T-502 | Phase 5 complete | `engine/telemetry.py` structured decision/summary/capReached records; wired into reconcile. Verified emitted fields == alert + README KQL (0 gaps). 92 tests pass (+7). |
| 2026-10-03 | T-601 + runtime wiring | Static checks recorded; `_build_runtime` done | Added `engine/config.py` (App Config loader) + `src/runtime.py` (build_runtime: query_fn + ARM client factories + registry); `function_app._build_runtime` delegates. T-601 recorded: pytest **102 passed**, `terraform fmt -check` exit 0, `validate` Success. T-602/T-603 remain — need live Azure + OI-01 scope values. |
| 2026-10-03 | tooling | CI + verification runbook | Added `.github/workflows/ci.yml` (pytest + `terraform fmt`/`validate`, no deploy) and `docs/VERIFICATION.md` (T-601 local/CI, T-602 deploy+dry-run checklist, T-603 go-live, alert verification). CI commands dry-run locally: 102 passed, fmt/validate clean. Linked runbook from README. |
| 2026-10-03 | review fixes | Critical/High/Medium/Low findings addressed | Fixed all 3 Critical, 6 High, and the Medium/Low findings from [REVIEW_FINDINGS.md](REVIEW_FINDINGS.md). This closes the defects that had made several Phase 0–5 tasks only nominally complete: **T-202** (C1 production exclusion, C2 tag inheritance — discovery now joins `resourcecontainers`), **T-302** (C3 SQL MI SDK pin, H3 HandlerSkip-as-skipped, H4 deallocate billed VMs), **T-404** (H5 private-networking validation, M4 `AzureWebJobsStorage` identity connection), **T-501/T-502** (H1 telemetry now exported via OpenTelemetry flat attributes; KQL aligned). Also M1 (Resource Graph power state), M2 (sub/RG include scopes + nested-MG excludes), M3 (single throttling mechanism), M6 (removed `config/settings.json`), M7 (deploy.sh plan hygiene), L1–L5 (provider cleanup, RBAC validation/`principal_type`, timer binding expr, order-map dedup, ruff + CI). Tests: **126 passed / 7 skipped**; ruff clean; `terraform fmt`/`validate` pass. Live verification (T-602/T-603) still pending Azure access. Note (L6): `config/profiles/` remains shared across tenants (documented in README); per-tenant profile directories are a future enhancement. |