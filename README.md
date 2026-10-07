# Azure Resource Power Scheduler

> Tag-driven start/stop scheduling for Azure resources (VM, VMSS, AKS, PostgreSQL/MySQL Flexible Server, SQL MI, Application Gateway), running as a timer-triggered Azure Function and deployed with Terraform.

**Last updated:** 2026-10-07 (v0.7 – large-tenant scaling: parallel submission, telemetry volume control, cap sizing) · **Requirements:** [docs/REQUIREMENTS.md](docs/REQUIREMENTS.md) · **Verification:** [docs/VERIFICATION.md](docs/VERIFICATION.md)

## Table of Contents

- [Quick Start](#quick-start)
- [How It Works](#how-it-works)
- [Repository Layout](#repository-layout)
- [Prerequisites](#prerequisites)
- [Deployment](#deployment)
  - [Step 1 – Sign in to Azure](#step-1--sign-in-to-azure)
  - [Step 2 – Bootstrap the Terraform state backend (one-time)](#step-2--bootstrap-the-terraform-state-backend-one-time)
  - [Step 3 – Configure the environment](#step-3--configure-the-environment)
  - [Step 4 – Deploy infrastructure with Terraform](#step-4--deploy-infrastructure-with-terraform)
  - [Step 5 – Deploy the function code](#step-5--deploy-the-function-code)
  - [Step 6 – Verify in dry-run mode](#step-6--verify-in-dry-run-mode)
  - [Step 7 – Go live](#step-7--go-live)
- [Configuration Reference](#configuration-reference)
- [Multiple Tenants](#multiple-tenants)
- [Large tenants](#large-tenants)
- [Day-2 Operations](#day-2-operations)
- [Rollback and Removal](#rollback-and-removal)
- [Troubleshooting](#troubleshooting)

---

## Quick Start

For an environment whose state backend already exists (see Step 2 for first-time setup):

```bash
az login --tenant <tenant-id>
export ARM_SUBSCRIPTION_ID=<management-subscription-id>

cd infra/scheduler
terraform init -backend-config=backend.hcl
terraform plan -out tfplan
terraform apply tfplan

cd ../../src
func azure functionapp publish "$(terraform -chdir=../infra/scheduler output -raw function_app_name)" --python
```

The scheduler starts in **dry-run mode**. It logs what it would do but changes nothing until you set `dry_run = false` ([Step 7](#step-7--go-live)).

## How It Works

1. A timer trigger runs the `reconcile` function every 15 minutes (UTC).
2. The function signs in with its **user-assigned managed identity**. No secrets are used.
3. It loads schedule profiles and scopes from **Azure App Configuration**.
4. It queries **Azure Resource Graph** across the in-scope management groups for resources tagged `schedule-profile`.
5. For each resource it computes the desired state (`Running` or `Stopped`) in the profile's timezone, compares it with the actual state, and submits start/stop operations only where they differ. It doesn't wait for completion; the next cycle verifies.
6. Every decision is logged to **Application Insights / Log Analytics**.

```
Management subscription (one scheduler for the whole tenant)
└── rg-pwrsched-<region>
    ├── func-pwrsched            (Flex Consumption, Python 3.11)
    ├── stpwrsched               (runtime storage, deployment package)
    ├── id-pwrsched              (user-assigned managed identity)
    ├── appcs-pwrsched           (App Configuration: profiles, scopes, settings)
    ├── appi-pwrsched            (Application Insights → Log Analytics)
    └── ag-pwrsched              (alert action group)

Custom role "Resource Power Operator" → assigned to id-pwrsched
at the in-scope management groups (e.g. Landing Zones, Sandbox).

Names take an optional `name_suffix` (e.g. func-pwrsched-sea) only if you run
more than one instance; it is empty by default.
```

## Repository Layout

```
azure-power-scheduler/
├── README.md
├── docs/
│   ├── REQUIREMENTS.md
│   ├── VERIFICATION.md             # live verification runbook + status tracker
│   ├── presentations/              # solution decks
│   └── archive/                    # finished implementation docs (tasks, code review)
├── config/                         # Loaded into App Configuration by Terraform
│   └── profiles/                   # schedule profiles (settings come from tfvars)
│       ├── weekday-0830-1730.json   # standard: 08:30–17:30 Mon–Fri, Asia/Bangkok
│       └── sandbox-default.json
├── infra/
│   ├── scheduler/                  # single tenant-wide root module
│   │   ├── backend.hcl.example
│   │   ├── main.tf
│   │   ├── providers.tf
│   │   ├── variables.tf
│   │   ├── outputs.tf
│   │   └── terraform.tfvars.example
│   └── modules/
│       ├── function_app/           # plan, function app, storage, identity, networking
│       ├── rbac/                   # custom role definition + MG assignments
│       ├── app_config/             # store + keys from /config
│       └── monitoring/             # App Insights, alerts, action group
├── src/                            # Azure Function (Python 3.11)
│   ├── function_app.py             # timer trigger (HTTP on-demand trigger: phase 2)
│   ├── engine/                     # discovery, desired-state evaluation, ordering
│   ├── handlers/                   # vm.py, aks.py, postgres_flex.py, ...
│   ├── host.json
│   └── requirements.txt
└── tests/
```

## Prerequisites

### Tools

| Tool | Minimum version | Check |
|---|---|---|
| Terraform | 1.9 | `terraform version` |
| Azure CLI | 2.60 | `az version` |
| Azure Functions Core Tools | 4.x (recent release with Flex Consumption support) | `func --version` |
| Python | 3.11 | `python3 --version` |

### Permissions for the person running Terraform

| Scope | Role | Why |
|---|---|---|
| Management subscription | Owner, or Contributor + User Access Administrator | Create resources and role assignments |
| Each in-scope management group (e.g. Landing Zones, Sandbox) | Owner, or User Access Administrator + permission to write role definitions | Create the custom role and assign it to the managed identity |
| State storage account | Storage Blob Data Contributor | Read/write Terraform state with Entra ID auth |

> 📝 Note: Terraform grants the deployer **App Configuration Data Owner** on the store (so it can write configuration keys) and the runtime storage account data roles — **Storage Blob Data Owner**, **Storage Queue Data Contributor** and **Storage Table Data Contributor** — so it can read/write that account over the data plane with shared keys disabled (SEC-005). You only need to grant yourself **Storage Blob Data Contributor** on the *state* storage account by hand (Step 2), because that account exists before Terraform runs. Role propagation can take a few minutes; see [Troubleshooting](#troubleshooting) if the first apply returns `403`.

### Network

If you enable private networking (`enable_private_networking = true`), run Terraform from a machine that can reach the App Configuration private endpoint (for example a jump host or self-hosted runner in a spoke peered to the hub), because Terraform writes App Configuration keys over the data plane.

## Deployment

### Step 1 – Sign in to Azure

```bash
az login --tenant <tenant-id>
az account set --subscription <management-subscription-id>

# azurerm provider 4.x requires the subscription to be set explicitly
export ARM_SUBSCRIPTION_ID=<management-subscription-id>
export ARM_TENANT_ID=<tenant-id>
```

**Expected output:** `az account show --query name -o tsv` prints the Management subscription name.

### Step 2 – Bootstrap the Terraform state backend (one-time)

Skip this step if your organisation already has a Terraform state storage account.

```bash
LOCATION=<region>                 # e.g. southeastasia
STATE_RG=rg-tfstate-mgmt
STATE_SA=sttfstatemgmt$RANDOM     # must be globally unique, 3–24 lowercase alphanumerics
STATE_CONTAINER=tfstate

az group create --name "$STATE_RG" --location "$LOCATION"

az storage account create \
  --name "$STATE_SA" \
  --resource-group "$STATE_RG" \
  --location "$LOCATION" \
  --sku Standard_ZRS \
  --kind StorageV2 \
  --min-tls-version TLS1_2 \
  --allow-blob-public-access false \
  --allow-shared-key-access false

az storage account blob-service-properties update \
  --account-name "$STATE_SA" --resource-group "$STATE_RG" \
  --enable-versioning true --enable-delete-retention true --delete-retention-days 30

# Allow yourself to read/write state with Entra ID
az role assignment create \
  --assignee "$(az ad signed-in-user show --query id -o tsv)" \
  --role "Storage Blob Data Contributor" \
  --scope "$(az storage account show -n "$STATE_SA" -g "$STATE_RG" --query id -o tsv)"

az storage container create --name "$STATE_CONTAINER" \
  --account-name "$STATE_SA" --auth-mode login

echo "State storage account: $STATE_SA"
```

**If container creation fails with `AuthorizationPermissionMismatch`:** wait 1–2 minutes for the role assignment to propagate, then retry.

### Step 3 – Configure the deployment

```bash
cd infra/scheduler
cp backend.hcl.example backend.hcl
cp terraform.tfvars.example terraform.tfvars
```

Edit **`backend.hcl`**:

```hcl
resource_group_name  = "rg-tfstate-mgmt"
storage_account_name = "<state-storage-account-name>"
container_name       = "tfstate"
key                  = "pwrsched/terraform.tfstate"
use_azuread_auth     = true
```

Edit **`terraform.tfvars`**:

```hcl
subscription_id = "<management-subscription-id>"
location        = "<region>"

# Optional. Leave empty for the standard single tenant-wide deployment;
# set a short suffix only if you run more than one instance (e.g. "sea").
name_suffix = ""

# Parent (assignable) scope for the custom role definition.
role_assignable_scope = "/providers/Microsoft.Management/managementGroups/<org>"

in_scope_management_group_ids = [
  "/providers/Microsoft.Management/managementGroups/<org>-landingzones",
  "/providers/Microsoft.Management/managementGroups/<org>-sandbox",
]

excluded_scope_ids = [
  "/providers/Microsoft.Management/managementGroups/<org>-platform",
]

enabled_resource_types = ["vm", "vmss", "aks", "postgres-flex", "mysql-flex", "sqlmi"]

reconcile_schedule  = "0 */15 * * * *"   # NCRONTAB, UTC
dry_run             = true               # keep true until verified
max_actions_per_run = 200

log_analytics_workspace_id = "/subscriptions/<id>/resourceGroups/<rg>/providers/Microsoft.OperationalInsights/workspaces/<name>"
alert_email_addresses      = ["cloud-platform@example.com"]

enable_private_networking = false
# integration_subnet_id   = "/subscriptions/<id>/resourceGroups/<rg>/providers/Microsoft.Network/virtualNetworks/<vnet>/subnets/<snet>"

tags = {
  owner       = "cloud-platform"
  cost-centre = "<cc>"
  project     = "power-scheduler"
  managed-by  = "terraform"
}
```

Review the schedule profiles in `config/profiles/` before deploying (see [Configuration Reference](#configuration-reference)).

> ⚠️ Warning: Do not commit `backend.hcl` or `terraform.tfvars` if they contain environment-specific identifiers your organisation treats as sensitive. Both are listed in `.gitignore`.

### Step 4 – Deploy infrastructure with Terraform

Run from `infra/scheduler`:

```bash
terraform init -backend-config=backend.hcl
terraform fmt -check -recursive ../
terraform validate
terraform plan -out tfplan
```

Review the plan. For a first deployment you should see creations of roughly these resources:

- resource group, storage account and container, user-assigned identity;
- Flex Consumption plan and Function App;
- App Configuration store and keys (one per profile and setting);
- Application Insights, alert rules and action group;
- custom role definition **Resource Power Operator**;
- one role assignment per in-scope management group;
- data-plane role assignments (App Configuration Data Reader and Storage roles for the identity; App Configuration Data Owner and the runtime storage Blob/Queue/Table data roles for you).

Make sure the plan contains **no** role assignment at the Platform MG or the Tenant Root Group. Then apply:

```bash
terraform apply tfplan
terraform output
```

**Expected output:** `Apply complete!`, followed by outputs similar to:

```
function_app_name            = "func-pwrsched"
resource_group_name          = "rg-pwrsched-<region>"
app_configuration_endpoint   = "https://appcs-pwrsched.azconfig.io"
managed_identity_principal_id = "<guid>"
application_insights_name    = "appi-pwrsched"
```

### Step 5 – Deploy the function code

Terraform creates the empty Function App. Publish the code with Azure Functions Core Tools. It runs a remote build that installs `requirements.txt` on Azure.

```bash
cd ../../src
FUNC_APP=$(terraform -chdir=../infra/scheduler output -raw function_app_name)

func azure functionapp publish "$FUNC_APP" --python
```

Alternatively, deploy a zip with the Azure CLI:

```bash
RG=$(terraform -chdir=../infra/scheduler output -raw resource_group_name)
zip -r ../function.zip . -x "*.pyc" "__pycache__/*" ".venv/*" "local.settings.json"
az functionapp deployment source config-zip \
  --resource-group "$RG" --name "$FUNC_APP" --src ../function.zip --build-remote true
```

**Expected output:** the publish log ends with the list of functions:

```
Functions in func-pwrsched:
    reconcile - [timerTrigger]
```

Re-run this step whenever the code in `src/` changes. Configuration changes do **not** need a code redeploy.

### Step 6 – Verify in dry-run mode

Wait for the next 15-minute tick, then query the logs. Use the **Logs** blade of the Application Insights resource (which uses the classic `traces` / `customDimensions` schema), or the CLI against the backing Log Analytics workspace. The scheduler's Application Insights is **workspace-based**, so from the CLI you query the workspace tables — `AppTraces`, with custom dimensions under `Properties[...]` and the timestamp in `TimeGenerated` — not the classic `traces` / `customDimensions` the `az monitor app-insights query` command reads (that command returns no rows against a workspace-based resource):

```bash
RG=$(terraform -chdir=../infra/scheduler output -raw resource_group_name)
WS=$(az monitor log-analytics workspace show \
       -g "$RG" --workspace-name log-pwrsched --query customerId -o tsv)

az monitor log-analytics query --workspace "$WS" --analytics-query '
AppTraces
| where TimeGenerated > ago(1h)
| where Properties["pwrsched.event"] == "pwrsched.decision"
| project TimeGenerated,
          resource = tostring(Properties["pwrsched.resourceId"]),
          profile  = tostring(Properties["pwrsched.profile"]),
          desired  = tostring(Properties["pwrsched.desiredState"]),
          actual   = tostring(Properties["pwrsched.actualState"]),
          action   = tostring(Properties["pwrsched.action"]),
          dryRun   = tostring(Properties["pwrsched.dryRun"])
| order by TimeGenerated desc' -o table
```

> 📝 Note: The alert rules and the Azure Monitor workbook are scoped to the
> Application Insights resource and use the classic `traces` / `customDimensions`
> schema — leave them as they are. Only the **CLI** reads the workspace tables
> (`AppTraces` / `Properties` / `TimeGenerated`). The portal **Logs** blade works
> either way depending on which resource you open it from.

Check that:

- [ ] a cycle summary appears every 15 minutes;
- [ ] only tagged resources from the in-scope MGs appear;
- [ ] no Platform MG resources appear;
- [ ] resources in subscriptions tagged `environment=prod` are logged with reason `production-excluded` and never acted on;
- [ ] `desired` matches what you expect for the current local time of each profile;
- [ ] `dryRun` is `true` and no start/stop entries appear in the Activity Log for the managed identity.

### Step 7 – Go live

After at least one full business day of correct dry-run results:

```bash
cd infra/scheduler
# set dry_run = false in terraform.tfvars
terraform plan -out tfplan    # should change only the App Configuration key pwrsched:dryRun
terraform apply tfplan
```

The change takes effect on the next cycle. Watch the first live cycles in the logs and in the Activity Log.

## Multiple Tenants

Deploy **one scheduler per tenant**. The Terraform code (`infra/scheduler` + `infra/modules`) and the Function code are identical for every tenant — only the configuration and the Terraform state differ. Do **not** use a git branch per tenant; keep one `main` branch and distinguish tenants by config files.

Per-tenant files live in `infra/tenants/` (copy the committed `.example` templates; the real files are gitignored):

```bash
cd infra/tenants
cp example.tfvars.example       contoso.tfvars
cp example.backend.hcl.example  contoso.backend.hcl
# edit both for the Contoso tenant (subscription, scopes, state storage account)
```

Each tenant keeps an **isolated state file** in a state storage account inside that tenant's own management subscription, so tenants never share state or access each other.

Sign in to the **target tenant**, then deploy with the wrapper:

```bash
az login --tenant <contoso-tenant-id>
export ARM_SUBSCRIPTION_ID=<contoso-management-subscription-id>
export ARM_TENANT_ID=<contoso-tenant-id>

./infra/deploy.sh contoso plan
./infra/deploy.sh contoso apply
```

`deploy.sh <tenant> <command>` runs `terraform -chdir=infra/scheduler` with that tenant's `-backend-config` and `-var-file` (`init` uses `-reconfigure` to switch backends cleanly between tenants). Commands: `init`, `plan`, `apply`, `output`, `destroy`.

Then publish the function code to that tenant's app:

```bash
cd src
FUNC_APP=$(terraform -chdir=../infra/scheduler output -raw function_app_name)
func azure functionapp publish "$FUNC_APP" --python
```

> 📝 Note: Production is hard-excluded in **every** tenant (subscriptions tagged `environment=prod`), regardless of configuration.

> 📝 Note: **Schedule profiles in `config/profiles/` are shared across all tenants** — the same profile files are loaded into every tenant's App Configuration. Per-tenant settings (scopes, enabled types, dry-run) differ via each tenant's `.tfvars`, but the profiles do not. If a tenant needs a different schedule, add a new profile file (used only where its name is tagged) rather than editing a shared one; per-tenant profile directories are a possible future enhancement (finding L6).

> ⚠️ Warning: Always confirm you are logged in to the correct tenant before `apply`. `deploy.sh` re-initialises the backend for the named tenant, but it cannot verify your Azure CLI session points at the same tenant.

## Configuration Reference

### Resource tags (set by workload owners)

| Tag | Example | Effect |
|---|---|---|
| `schedule-profile` | `weekday-0830-1730` | Opts the resource in. Can be set on a resource, resource group or subscription; the most specific wins. |
| `schedule-enabled` | `false` | Temporarily opts out |
| `schedule-override-state` | `running` or `stopped` | State to hold during an override (default `running`) |
| `schedule-override-until` | `2026-10-10T21:00+07:00` | End of the override; the schedule resumes after this time (include the UTC offset) |
| `schedule-order` | `1` | Start order (1 = first). Stop runs in reverse. |

> 📝 Note: Production subscriptions (tagged `environment=prod`) are always excluded. Tagging production resources has no effect.

### Schedule profile (`config/profiles/<name>.json`)

The standard profile, `config/profiles/weekday-0830-1730.json`:

```json
{
  "timezone": "Asia/Bangkok",
  "runWindows": [
    { "days": ["Mon", "Tue", "Wed", "Thu", "Fri"], "start": "08:30", "stop": "17:30" }
  ],
  "startOffsetMinutesByOrder": { "1": -30, "2": -15, "3": 0 }
}
```

The file name (without `.json`) is the profile name used in the `schedule-profile` tag. With these offsets, databases (order 1) start at 08:00, AKS and Application Gateway (order 2) at 08:15, and VMs (order 3) at 08:30. Everything stops at 17:30, in reverse order.

> 📝 Note: Public holidays are not handled in phase 1; resources follow the weekday schedule. For a long holiday, set a `stopped` override (see [Ad-hoc start or stop](#ad-hoc-start-or-stop-override)). Azure SQL Database is not supported.

### Terraform variables

| Variable | Description | Default | Required |
|---|---|---|---|
| `subscription_id` | Management subscription for the scheduler | – | ✓ |
| `location` | Azure region | – | ✓ |
| `name_suffix` | Optional short suffix for resource names; empty for the single tenant-wide instance | `""` | |
| `role_assignable_scope` | Parent (intermediate/org) MG that is the assignable scope for the custom role | – | ✓ |
| `in_scope_management_group_ids` | MGs to query and assign the custom role at | – | ✓ |
| `excluded_scope_ids` | MG/subscription/RG IDs always skipped | `[]` | |
| `enabled_resource_types` | Handler keys to enable | `["vm"]` | |
| `reconcile_schedule` | NCRONTAB timer expression (UTC) | `0 */15 * * * *` | |
| `scheduler_enabled` | Set `false` to disable the timer function | `true` | |
| `dry_run` | Log only, no actions | `true` | |
| `max_actions_per_run` | Safety cap per cycle; single combined start/stop cap (D-09). Size from the measured peak (see [Large tenants](#large-tenants)) | `200` | |
| `max_parallel_actions` | Parallel start/stop submissions per order group (FR-034); submission is parallel within an order group with a barrier between groups | `10` | |
| `log_converged_decisions` | Emit a per-resource decision record for already-converged (no-op) resources; set `false` above ~1,000 resources to control log ingestion (NFR-011) | `true` | |
| `log_analytics_workspace_id` | Existing workspace; creates one if empty | `""` | |
| `enable_private_networking` | Private endpoints + VNet integration | `false` | |
| `integration_subnet_id` | Subnet for VNet integration (delegated to `Microsoft.App/environments`) | `null` | when private |
| `alert_email_addresses` | Alert recipients | `[]` | |
| `tags` | Standard resource tags | `{}` | ✓ |

## Large tenants

The defaults are tuned for small-to-medium tenants. For large estates (hundreds
to thousands of in-scope resources, up to the NFR-002 target of 5,000), apply the
guidance below. All of it is configuration — no code change.

### Size the safety cap from the measured peak

`max_actions_per_run` is a single combined start/stop cap (decision **D-09**): a
**safety brake** against mass mis-tagging, not a throughput knob. Size it from
the busiest real cycle, not guesswork. During the dry-run week, run this query
(the peak is almost always the 17:30 stop, when nearly everything transitions at
once) against the backing Log Analytics workspace:

```kusto
AppTraces
| where Properties["pwrsched.event"] == "pwrsched.decision"
| where tostring(Properties["pwrsched.action"]) in ("start", "stop")
| summarize actions = count()
    by runId = tostring(Properties["pwrsched.runId"]), bin(TimeGenerated, 15m)
| top 5 by actions desc
```

Set `max_actions_per_run ≈ peak × 1.2` (headroom for growth). Keep it as a brake:
if a cycle ever hits the cap in normal operation, investigate mis-tagging before
raising it. A `pwrsched.capReached` alert (OBS-005) fires when the cap truncates
a cycle.

### Submission throughput and the function timeout

Within a cycle, start/stop operations are **submitted in parallel** through a
bounded pool (`max_parallel_actions`, default 10), per order group with a barrier
between groups — so dependency ordering (databases before apps on start, the
reverse on stop) is preserved while the capped set is submitted quickly
(FR-034). Submission is asynchronous (the next cycle confirms completion), so the
per-action cost is one ARM call, not the minutes a start/stop takes to finish.

The whole cycle must finish inside `functionTimeout` (`src/host.json`, **12
minutes**) and before the next cycle. **Rule: the function timeout must be less
than the `reconcile_schedule` interval** (12 min < the default 15 min). If you
shorten the interval, lower the timeout to match. Raise `max_parallel_actions`
only if you also confirm the subscription's ARM write limits tolerate it (see
below); 10–20 is a sensible range.

### Control telemetry ingestion

By default every evaluated resource emits one decision record per cycle. At 5,000
resources × 96 cycles/day that is ~480,000 records/day (~hundreds of MB). Above
~1,000 in-scope resources, set `log_converged_decisions = false`: the scheduler
then **suppresses the per-resource `already-converged` no-op records** and relies
on the per-cycle summary, which carries `converged`, `desiredRunning` and
`desiredStopped` counts (NFR-011, OBS-002). All actionable results — start, stop,
skipped, excluded, failed, production-excluded — are still logged individually.
The savings/hours-saved reporting works from the summary counts either way.
Review Application Insights ingestion after the first week and set a Log
Analytics daily cap if needed. The **summary workbook**
(`infra/workbooks/pwrsched-summary.workbook.json`) is built for this mode — it
reads the per-cycle summary record, so it stays fast with thousands of resources.

### Lower the peak itself

- **Stagger profiles by business unit** so the whole estate does not transition
  in one cycle — e.g. `weekday-0800-1700`, `weekday-0815-1715`,
  `weekday-0830-1730`, `weekday-0845-1745`. This is the most effective lever: it
  cuts the per-cycle peak directly, which lowers the required cap and the
  submission time.
- **ARM write limits are per subscription.** A very large single subscription
  transitions more slowly regardless of `max_parallel_actions`; spreading
  workloads across subscriptions (or staggering their profiles) helps.



### Change a schedule

```bash
vi config/profiles/weekday-0830-1730.json     # e.g. change "stop" to "17:00"
cd infra/scheduler && terraform plan -out tfplan && terraform apply tfplan
```

### Add a new profile

Create `config/profiles/<new-name>.json`, apply, then tag resources with `schedule-profile=<new-name>`.

### Change scope (management group / subscription / resource group)

Edit `in_scope_management_group_ids` and/or `excluded_scope_ids` in `terraform.tfvars`, then plan and apply. Adding an MG also creates the custom role assignment there.

> 📝 Note: To schedule only one subscription or resource group inside an in-scope MG, either tag only that subscription/RG, or add its siblings to `excluded_scope_ids`.

### Enable another resource type

Add the handler key (for example `sqlmi` or `appgw`) to `enabled_resource_types`, then plan and apply. Terraform adds the matching permissions to the custom role. If the handler is new code, deploy the code first (Step 5).

### Onboard resources (workload owners)

```bash
# Tag a whole resource group
az tag update --operation Merge \
  --resource-id "/subscriptions/<sub-id>/resourceGroups/<rg>" \
  --tags schedule-profile=weekday-0830-1730

# Make the database start first
az tag update --operation Merge --resource-id "<postgres-flex-resource-id>" --tags schedule-order=1
```

### Ad-hoc start or stop (override)

Phase 1 has no on-demand endpoint (planned for phase 2). To start or stop resources outside the schedule, set an override. The next cycle (within 15 minutes) applies it, and the schedule resumes when it expires.

```bash
RID="/subscriptions/<sub-id>/resourceGroups/<rg>"      # resource, resource group or subscription
UNTIL=$(TZ=Asia/Bangkok date -d '+4 hours' +%Y-%m-%dT%H:%M+07:00)   # GNU date; macOS: TZ=Asia/Bangkok date -v+4H +%Y-%m-%dT%H:%M+07:00

# Keep running (e.g. work late or at the weekend)
az tag update --operation Merge --resource-id "$RID" \
  --tags schedule-override-state=running schedule-override-until="$UNTIL"

# Keep stopped (e.g. not needed this afternoon)
az tag update --operation Merge --resource-id "$RID" \
  --tags schedule-override-state=stopped schedule-override-until="$UNTIL"

# Cancel an override early
az tag update --operation Delete --resource-id "$RID" \
  --tags schedule-override-state schedule-override-until
```

> 📝 Note: Overrides on a resource group or subscription apply to every tagged resource inside it. Expired override tags are ignored, so removing them is optional.

### Opt out temporarily

```bash
az tag update --operation Merge --resource-id "<resource-id>" --tags schedule-enabled=false
```

## Rollback and Removal

| Situation | Action |
|---|---|
| Unexpected actions — stop acting immediately | Set `dry_run = true` and apply. This takes effect on the next cycle. For an instant stop: `az functionapp config appsettings set -g "$RG" -n "$FUNC_APP" --settings AzureWebJobs.reconcile.Disabled=true`, then set `scheduler_enabled = false` in tfvars and apply so Terraform matches. |
| Bad code release | Re-publish the previous code version (Step 5) from the previous Git tag. |
| Bad configuration | `git revert` the change in `config/` or `terraform.tfvars`, then plan and apply. |
| Remove the solution | `terraform destroy` from `infra/scheduler`. This removes the Function App, configuration, custom role and its assignments. Resources stay in whatever power state they were in; start any that need to be running. Tags on workload resources are not removed. |

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `terraform init` fails with `403 AuthorizationPermissionMismatch` | No Storage Blob Data Contributor on the state account, or not yet propagated | Assign the role (Step 2) and wait a few minutes |
| `terraform apply` fails writing App Configuration keys with `403` | Data Owner role assigned in the same apply has not propagated | Wait 2–5 minutes and run `terraform apply` again |
| `terraform plan`/`apply` fails reading the runtime storage account with `403 KeyBasedAuthenticationNotPermitted` | The deployer's Blob/Queue/Table data roles on the runtime storage account were assigned in the same apply and have not propagated | Wait 2–5 minutes and re-run; the roles are granted by Terraform (DP-01) |
| `terraform apply` fails creating the role definition or assignment at an MG | Missing permissions at the management group | Ask for Owner / User Access Administrator at that MG (see Prerequisites) |
| App Configuration keys time out during apply | Private networking enabled and no private connectivity from your machine | Run Terraform from a host with access to the private endpoint |
| `func ... publish` fails: "Can't find app" | Wrong subscription selected in the CLI | `az account set --subscription <management-subscription-id>` |
| No log entries after 15 minutes | Function not deployed, timer disabled, or app failing at start-up | Check `func azure functionapp list-functions "$FUNC_APP"` and the `exceptions` table in Application Insights |
| Resource never acted on | Tag missing or misspelled, profile name unknown, resource under an excluded scope, or type not enabled | Look for its `resourceId` in the decision logs; the `action`/`reason` fields explain the skip |
| `AuthorizationFailed` on start/stop | Custom role lacks the action, or the MG is not in `in_scope_management_group_ids` | Add the resource type or scope and apply; role changes can take a few minutes |
| PostgreSQL/MySQL server running again after a week | Platform auto-restart after 7 days stopped | Expected; the next cycle stops it again |
| AKS start slow / apps unavailable at start of day | AKS start takes 5–10 minutes | Give AKS a negative start offset via `schedule-order` and `startOffsetMinutesByOrder` |
