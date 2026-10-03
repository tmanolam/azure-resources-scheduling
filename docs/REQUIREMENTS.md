# Requirements Specification: Azure Resource Power Scheduler

| Item | Value |
|---|---|
| Document ID | AZ-PWRSCHED-RS-001 |
| Version | 0.1 (Draft for review) |
| Last updated | 2026-10-03 |
| Selected option | Option C – Azure Functions (timer-triggered reconciliation engine) |
| Infrastructure as Code | Terraform (`azurerm` provider 4.x) |
| Status | Draft – pending stakeholder review |

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Business Objectives and Success Metrics](#2-business-objectives-and-success-metrics)
3. [Scope](#3-scope)
4. [Stakeholder Register](#4-stakeholder-register)
5. [Context and Target Architecture](#5-context-and-target-architecture)
6. [Configuration Model](#6-configuration-model)
7. [Functional Requirements](#7-functional-requirements)
8. [Resource Type Handler Requirements](#8-resource-type-handler-requirements)
9. [Business Rules](#9-business-rules)
10. [Non-Functional Requirements](#10-non-functional-requirements)
11. [Security Requirements](#11-security-requirements)
12. [Observability Requirements](#12-observability-requirements)
13. [Infrastructure as Code (Terraform) Requirements](#13-infrastructure-as-code-terraform-requirements)
14. [User Stories and Acceptance Criteria](#14-user-stories-and-acceptance-criteria)
15. [Assumptions and Dependencies](#15-assumptions-and-dependencies)
16. [Risks](#16-risks)
17. [Open Issues and Gaps](#17-open-issues-and-gaps)
18. [Glossary](#18-glossary)

---

## 1. Executive Summary

The organisation runs non-production workloads in Azure spoke subscriptions under a Cloud Adoption Framework (CAF) management group hierarchy with a hub/spoke network. Many of these workloads run 24×7 although they are used only during business hours.

This specification defines a centrally managed **Resource Power Scheduler**. It automatically starts and stops supported Azure resources according to configurable schedules. The solution is an Azure Function App on a timer trigger, deployed with Terraform into the Management subscription. On each run it compares the desired power state of every opted-in resource with its actual state and corrects the difference (**reconciliation**).

The scheduler is flexible in three ways:

- **Schedule:** schedules are named profiles that can be changed without code changes.
- **Resource type:** the resource types in scope can be selected (VM, AKS, databases and others).
- **Scope:** scope can be set at management group, subscription or resource group level.

## 2. Business Objectives and Success Metrics

| ID | Objective | Success metric |
|---|---|---|
| OBJ-01 | Reduce compute cost of non-production workloads | ≥ 40% reduction in compute cost for in-scope resources within 3 months of rollout |
| OBJ-02 | Remove manual start/stop effort | Zero manual start/stop tickets for onboarded workloads |
| OBJ-03 | Change schedules quickly and safely | Schedule change effective within 1 reconciliation cycle (≤ 15 min) after deployment |
| OBJ-04 | Protect shared platform services | Zero incidents caused by the scheduler affecting Platform MG resources |
| OBJ-05 | Provide transparency | 100% of actions logged and queryable; monthly savings report available |

## 3. Scope

### 3.1 In scope

- Scheduled start/stop (power management) of the resource types listed in [Section 8](#8-resource-type-handler-requirements).
- Scope selection at management group, subscription and resource group level, with include and exclude lists.
- Tag-based opt-in, opt-out and temporary override per resource, resource group or subscription.
- Named, timezone-aware schedule profiles, including weekdays, run windows and holiday calendars.
- Dry-run mode (evaluate and log only, no changes).
- On-demand execution through an authenticated HTTP endpoint.
- Logging, alerting and reporting.
- Terraform code for all infrastructure, identity, RBAC and configuration.
- A README with Terraform CLI deployment steps.

### 3.2 Out of scope

- Scheduling of Platform MG resources (Connectivity, Identity, Management): Azure Firewall, VPN/ExpressRoute gateways, Bastion, domain controllers, DNS resolvers.
- Scaling or rightsizing logic beyond the actions defined in Section 8 (for example autoscale rules or SKU recommendations).
- Deletion or re-creation of resources.
- CI/CD pipeline automation (Jenkins or other). Deployment is by Terraform CLI in this phase.
- A self-service web portal UI (possible future phase).
- Production workloads, unless explicitly opted in (see BR-003).

## 4. Stakeholder Register

| Role | Interest | Responsibility |
|---|---|---|
| Cloud Platform Team | Owns the scheduler, platform safety | Build, deploy, operate; approve scope changes |
| FinOps / Cost Management | Cost savings | Define savings targets, consume reports |
| Application / Workload Owners | Availability during working hours | Tag resources, choose profiles, request overrides |
| Security / Governance | Least privilege, auditability | Approve RBAC model and custom role |
| Operations / Service Desk | Incident handling | Use runbooks; handle "resource not started" issues |

## 5. Context and Target Architecture

### 5.1 Landing zone context

```
Tenant Root Group
└── <org> (intermediate root MG)
    ├── Platform MG ............ EXCLUDED from scheduling
    │   ├── Connectivity (hub VNet, Firewall, Gateways, DNS)
    │   ├── Identity
    │   └── Management  ......... Scheduler is deployed here
    ├── Landing Zones MG ....... IN SCOPE (custom role assigned here)
    │   ├── Corp   (spoke subscriptions)
    │   └── Online (spoke subscriptions)
    ├── Sandbox MG ............. IN SCOPE (default schedule)
    └── Decommissioned MG ...... EXCLUDED
```

### 5.2 Solution components

| Component | Purpose |
|---|---|
| Resource group `rg-pwrsched-<env>-<region>` | Holds all scheduler resources (Management subscription) |
| Function App (Flex Consumption, Linux, Python 3.11) | Hosts the timer-triggered reconciliation function and the HTTP on-demand function |
| Storage account | Functions runtime storage (`AzureWebJobsStorage`), deployment package container, timer lease |
| User-assigned managed identity | Identity used for Azure Resource Manager (ARM), Resource Graph, App Configuration and Storage access |
| Azure App Configuration | Stores schedule profiles, scope include/exclude lists and global settings |
| Application Insights + Log Analytics workspace | Telemetry, action audit log, alerts (may reuse the central Management workspace) |
| Custom role "Resource Power Operator" | Least-privilege start/stop permissions, assigned at in-scope MGs |
| Action group | Alert notifications (email / Teams) |

### 5.3 Execution flow

```mermaid
flowchart TD
    T[Timer trigger every 15 min UTC] --> A[Acquire token via managed identity]
    A --> B[Load profiles and scopes from App Configuration]
    B --> C[Query Azure Resource Graph at included scopes]
    C --> D[Filter: exclusions, enabled tag, resource types]
    D --> E[Evaluate desired state per resource<br/>profile + timezone + holidays + override]
    E --> F[Read actual power state]
    F --> G{desired != actual?}
    G -- No --> L[Log: no action]
    G -- Yes --> H[Order actions: start ascending, stop descending]
    H --> I{Dry run?}
    I -- Yes --> L2[Log: would start/stop]
    I -- No --> J[Submit ARM long-running operation, no wait]
    J --> L3[Log action + result]
```

## 6. Configuration Model

### 6.1 Resource tags

Tags can be set on a resource, a resource group or a subscription. The **most specific** value wins: resource, then resource group, then subscription.

| Tag key | Allowed values | Required | Description |
|---|---|---|---|
| `schedule-profile` | Name of a defined profile | Yes (to opt in) | Schedule profile applied to the resource |
| `schedule-enabled` | `true` \| `false` | No (default `true` when a profile is set) | Opt out without removing the profile |
| `schedule-override-until` | ISO 8601 date-time with offset, e.g. `2026-10-10T18:00+07:00` | No | Keep the resource **running** until this time, then resume the schedule |
| `schedule-order` | Integer 1–9 | No (default per type, see 8.2) | Start order (ascending); stop runs in reverse |

### 6.2 Schedule profile schema (App Configuration)

Profiles are stored as JSON values under the key prefix `pwrsched:profiles:<name>`.

```json
{
  "timezone": "<IANA timezone, e.g. Europe/London>",
  "runWindows": [
    { "days": ["Mon", "Tue", "Wed", "Thu", "Fri"], "start": "08:00", "stop": "20:00" }
  ],
  "holidayCalendar": "public-2026",
  "stopOnHolidays": true,
  "startOffsetMinutesByOrder": { "1": -30, "2": -15, "3": 0 }
}
```

Rules for profile values:

- `timezone` must be a valid IANA timezone name; each profile sets its own.
- Several `runWindows` per profile are allowed, for example a separate Saturday window.
- A window where `stop` is earlier than `start` crosses midnight (for example 20:00–02:00).
- `startOffsetMinutesByOrder` lets dependencies such as databases start earlier than the apps that use them.

### 6.3 Global settings (App Configuration)

| Key | Example | Description |
|---|---|---|
| `pwrsched:scopes:include` | `["/providers/Microsoft.Management/managementGroups/landingzones", "/providers/Microsoft.Management/managementGroups/sandbox"]` | Scopes to query |
| `pwrsched:scopes:exclude` | `["/providers/Microsoft.Management/managementGroups/platform"]` | Scopes always excluded (MG, subscription or RG IDs) |
| `pwrsched:resourceTypes` | `["vm","vmss","aks","postgres-flex","mysql-flex","sqlmi","appgw"]` | Enabled resource type handlers |
| `pwrsched:dryRun` | `true` | Global dry-run switch |
| `pwrsched:maxActionsPerRun` | `200` | Safety cap |
| `pwrsched:holidays:<calendar>` | `["2026-12-31","2027-01-01"]` | Holiday dates |

## 7. Functional Requirements

Priority uses MoSCoW: **M**ust, **S**hould, **C**ould, **W**on't (this phase).

### 7.1 Scheduling and execution

| ID | Requirement | Priority |
|---|---|---|
| FR-001 | The system shall run a reconciliation cycle on a timer, by default every 15 minutes. The interval shall be configurable through a Terraform variable (NCRONTAB expression in an app setting). | M |
| FR-002 | The system shall evaluate time in each profile's own IANA timezone, independently of the Function App timezone (UTC). | M |
| FR-003 | The system shall determine the desired state (`Running` or `Stopped`) of each resource from its profile, run windows, holiday calendar and override tag. | M |
| FR-004 | The system shall act only when the desired state differs from the actual state (idempotent reconciliation). | M |
| FR-005 | The system shall submit start/stop operations asynchronously (no wait for completion) and verify the outcome in the next cycle. | M |
| FR-006 | The system shall honour start ordering (ascending `schedule-order`) and stop ordering (descending), including per-order start offsets from the profile. | S |
| FR-007 | When a run was missed (`IsPastDue`), the system shall run immediately on recovery and reconcile to the current desired state. | M |

### 7.2 Scope and selection

| ID | Requirement | Priority |
|---|---|---|
| FR-010 | The system shall discover resources using Azure Resource Graph across all configured include scopes (management group, subscription or resource group). | M |
| FR-011 | The system shall always skip resources under any exclude scope, even when they are tagged. | M |
| FR-012 | The system shall process only resource types enabled in `pwrsched:resourceTypes`. | M |
| FR-013 | The system shall resolve tags with precedence resource > resource group > subscription. | M |
| FR-014 | The system shall handle Resource Graph paging (more than 1,000 results). | M |

### 7.3 Overrides and on-demand operations

| ID | Requirement | Priority |
|---|---|---|
| FR-020 | The system shall keep a resource running while `schedule-override-until` is in the future and resume the schedule after it expires. | M |
| FR-021 | The system shall skip resources tagged `schedule-enabled=false`. | M |
| FR-022 | The system shall expose an HTTP endpoint (`POST /api/run`) that accepts `action` (`start`/`stop`/`reconcile`), `scope`, `resourceTypes[]` and `dryRun`. | S |
| FR-023 | The HTTP endpoint shall require Microsoft Entra ID authentication and authorise callers by app role (e.g. `PowerScheduler.Operator`). | S |
| FR-024 | On-demand `start`/`stop` shall be one-off. The next scheduled cycle shall still apply the schedule unless an override tag is set. ⚠️ GAP: confirm expected behaviour (see OI-03). | S |

### 7.4 Safety

| ID | Requirement | Priority |
|---|---|---|
| FR-030 | The system shall support a global dry-run mode that logs intended actions without calling start/stop APIs. | M |
| FR-031 | The system shall stop processing actions after `maxActionsPerRun` is reached in one cycle and raise an alert. | M |
| FR-032 | The system shall refuse to act on a hard-coded deny list of resource types (Azure Firewall, virtual network gateways, Bastion, ExpressRoute circuits), regardless of configuration. | M |
| FR-033 | The system shall skip and log resources in a transitional state (e.g. `Starting`, `Stopping`, `Updating`) and retry in the next cycle. | M |

## 8. Resource Type Handler Requirements

### 8.1 Handler matrix

| Handler key | Azure resource type | Start action | Stop action | Default order | Priority |
|---|---|---|---|---|---|
| `vm` | `Microsoft.Compute/virtualMachines` | Start | **Deallocate** (not power-off) | 3 | M |
| `vmss` | `Microsoft.Compute/virtualMachineScaleSets` | Start | Deallocate | 3 | S |
| `aks` | `Microsoft.ContainerService/managedClusters` | Start cluster | Stop cluster | 2 | M |
| `postgres-flex` | `Microsoft.DBforPostgreSQL/flexibleServers` | Start | Stop | 1 | M |
| `mysql-flex` | `Microsoft.DBforMySQL/flexibleServers` | Start | Stop | 1 | M |
| `sqlmi` | `Microsoft.Sql/managedInstances` | Start | Stop | 1 | S |
| `appgw` | `Microsoft.Network/applicationGateways` | Start | Stop | 2 | C |
| `synapse-pool` | `Microsoft.Synapse/workspaces/sqlPools` | Resume | Pause | 1 | C |
| `sqldb` | `Microsoft.Sql/servers/databases` | Scale up to tagged SKU | Scale down to tagged SKU | 1 | W |
| `appservice` | `Microsoft.Web/serverfarms` | Scale up | Scale down | 3 | W |

### 8.2 Handler-specific requirements

| ID | Requirement |
|---|---|
| HR-001 | VM: stop shall use deallocate. VMs with ephemeral OS disks shall be skipped and logged as unsupported. |
| HR-002 | AKS: the handler shall read `powerState.code` and act only when the cluster `provisioningState` is `Succeeded`. |
| HR-003 | PostgreSQL/MySQL Flexible: the platform auto-starts servers after 7 days stopped. The reconciliation shall re-stop them when the desired state is `Stopped`. |
| HR-004 | Servers configured for high availability or with read replicas shall be handled per platform constraints. ⚠️ GAP: confirm whether HA servers are in scope (OI-04). |
| HR-005 | Each handler shall be a separate module implementing a common interface (`get_state`, `start`, `stop`) so new types can be added without changing the core engine. |

## 9. Business Rules

```
BR-001: Platform exclusion
Description : Resources under the Platform MG are never started or stopped.
Constraint  : Enforced by RBAC scope, exclude list and type deny list.
Source      : Cloud Platform Team

BR-002: Opt-in only
Description : A resource is managed only if a valid schedule-profile tag resolves for it.
Constraint  : Untagged resources are ignored.
Source      : Workload owners

BR-003: Production protection
Description : Resources in subscriptions tagged environment=prod are skipped unless
              schedule-allow-prod=true is set at subscription level.
Source      : Security / Governance

BR-004: Override precedence
Description : A valid future schedule-override-until always results in desired state Running.
Source      : Workload owners

BR-005: Unknown profile
Description : A tag referencing an undefined profile is treated as "no action" and logged as a warning.
Source      : Cloud Platform Team

BR-006: Reserved capacity
Description : Resources covered by Reserved Instances should not be onboarded.
Constraint  : Advisory; reported in the monthly savings report.
Source      : FinOps
```

## 10. Non-Functional Requirements

| ID | Category | Requirement |
|---|---|---|
| NFR-001 | Timeliness | A scheduled transition shall be **submitted** within 15 minutes of its scheduled time (one cycle). |
| NFR-002 | Performance | One cycle shall complete within 5 minutes for up to 2,000 in-scope resources. |
| NFR-003 | Reliability | Missed cycles shall self-heal on the next run (reconciliation). Failed actions shall be retried in each later cycle. |
| NFR-004 | Concurrency | Only one reconciliation cycle may run at a time (timer singleton lease). |
| NFR-005 | Throttling | The engine shall limit parallel ARM calls (default 10) and back off on HTTP 429 using the `Retry-After` header. |
| NFR-006 | Maintainability | New schedules or scopes shall require configuration changes only (Terraform `apply`), not code changes. |
| NFR-007 | Extensibility | New resource types shall be addable as a handler module plus a role-permission update. |
| NFR-008 | Cost | Run cost of the scheduler shall stay under USD 50/month (excluding a shared Log Analytics workspace). |
| NFR-009 | Testability | Desired-state evaluation shall be a pure function covered by unit tests (timezones, midnight crossing, holidays, overrides). |
| NFR-010 | Portability | All infrastructure shall be reproducible from Terraform in a new environment (e.g. dev and prod scheduler instances). |

## 11. Security Requirements

| ID | Requirement |
|---|---|
| SEC-001 | The Function App shall authenticate to Azure **only** through a user-assigned managed identity. No client secrets, connection strings or storage account keys. |
| SEC-002 | A custom role **Resource Power Operator** shall contain only read actions plus the start/stop actions of enabled handlers (see 11.1). |
| SEC-003 | The custom role shall be assigned only at in-scope management groups (Landing Zones, Sandbox), never at Tenant Root, the intermediate root or Platform. |
| SEC-004 | The managed identity shall have **App Configuration Data Reader** on the App Configuration store and the required Storage data roles on the runtime storage account. |
| SEC-005 | The storage account shall disable shared-key access and public blob access, and enforce TLS 1.2 or later. |
| SEC-006 | The Function App shall enforce HTTPS only, minimum TLS 1.2, FTP disabled, and Entra ID authentication on HTTP endpoints. |
| SEC-007 | Private endpoints and VNet integration shall be **configurable** (Terraform variable) for Storage and App Configuration to align with the hub/spoke design. |
| SEC-008 | All write actions shall be traceable in the Azure Activity Log under the managed identity and in the scheduler's own audit log. |

### 11.1 Custom role permissions (initial)

```
Microsoft.Resources/subscriptions/resourceGroups/read
Microsoft.ResourceGraph/resources/read
Microsoft.Compute/virtualMachines/read
Microsoft.Compute/virtualMachines/instanceView/read
Microsoft.Compute/virtualMachines/start/action
Microsoft.Compute/virtualMachines/deallocate/action
Microsoft.Compute/virtualMachineScaleSets/read
Microsoft.Compute/virtualMachineScaleSets/start/action
Microsoft.Compute/virtualMachineScaleSets/deallocate/action
Microsoft.ContainerService/managedClusters/read
Microsoft.ContainerService/managedClusters/start/action
Microsoft.ContainerService/managedClusters/stop/action
Microsoft.DBforPostgreSQL/flexibleServers/read
Microsoft.DBforPostgreSQL/flexibleServers/start/action
Microsoft.DBforPostgreSQL/flexibleServers/stop/action
Microsoft.DBforMySQL/flexibleServers/read
Microsoft.DBforMySQL/flexibleServers/start/action
Microsoft.DBforMySQL/flexibleServers/stop/action
Microsoft.Sql/managedInstances/read
Microsoft.Sql/managedInstances/start/action
Microsoft.Sql/managedInstances/stop/action
Microsoft.Network/applicationGateways/read
Microsoft.Network/applicationGateways/start/action
Microsoft.Network/applicationGateways/stop/action
```

> 📝 Note: Verify exact action names against the current Azure resource provider operations list before finalising the role. Add Synapse permissions only if the `synapse-pool` handler is enabled.

## 12. Observability Requirements

| ID | Requirement |
|---|---|
| OBS-001 | Each evaluated resource shall produce one structured log record: `runId`, `resourceId`, `type`, `profile`, `desiredState`, `actualState`, `action`, `dryRun`, `result`, `error`. |
| OBS-002 | Each cycle shall produce a summary record: counts of evaluated, started, stopped, skipped and failed resources, and duration. |
| OBS-003 | An alert shall fire when a cycle fails or does not run for more than 45 minutes. |
| OBS-004 | An alert shall fire when the same resource fails an action in 3 consecutive cycles. |
| OBS-005 | An alert shall fire when `maxActionsPerRun` is reached. |
| OBS-006 | An Azure Workbook (or saved KQL queries) shall show actions per subscription and estimated hours saved. |

## 13. Infrastructure as Code (Terraform) Requirements

| ID | Requirement |
|---|---|
| IAC-001 | All Azure resources, the role definition, role assignments and App Configuration keys shall be defined in Terraform. |
| IAC-002 | Terraform state shall be stored remotely in an Azure Storage backend with Entra ID authentication (`use_azuread_auth = true`) and state locking. |
| IAC-003 | The code shall be organised as a root module per environment plus reusable modules: `function_app`, `rbac`, `app_config`, `monitoring`. |
| IAC-004 | Schedule profiles and global settings shall be maintained in versioned files (`config/profiles/*.json`, `config/settings.json`) and loaded into App Configuration by Terraform. |
| IAC-005 | Provider versions shall be pinned (`azurerm ~> 4.x`, `azuread ~> 3.x`, Terraform `>= 1.9`). |
| IAC-006 | All resources shall carry standard tags: `environment`, `owner`, `cost-centre`, `project`, `managed-by=terraform`. |
| IAC-007 | Function code shall be packaged as a zip and deployed after infrastructure creation using the documented CLI command (see README). |
| IAC-008 | `terraform plan` shall show no changes after a successful apply (no drift-by-design), except for App Configuration keys changed intentionally. |

### 13.1 Key Terraform input variables

| Variable | Type | Description |
|---|---|---|
| `subscription_id` | string | Management subscription hosting the scheduler |
| `location` | string | Azure region |
| `environment` | string | `dev` / `prod` |
| `in_scope_management_group_ids` | list(string) | MGs where the custom role is assigned and resources are queried |
| `excluded_scope_ids` | list(string) | MG/subscription/RG IDs always excluded |
| `enabled_resource_types` | list(string) | Handler keys to enable |
| `reconcile_schedule` | string | NCRONTAB expression, default `0 */15 * * * *` |
| `dry_run` | bool | Global dry-run switch, default `true` |
| `max_actions_per_run` | number | Safety cap, default `200` |
| `log_analytics_workspace_id` | string | Existing central workspace (optional) |
| `enable_private_networking` | bool | Create private endpoints and VNet integration |
| `integration_subnet_id` | string | Subnet for Function App VNet integration (when private) |
| `alert_email_addresses` | list(string) | Action group recipients |
| `tags` | map(string) | Standard resource tags |

## 14. User Stories and Acceptance Criteria

### US-01 Scheduled stop of a VM

```
As a workload owner,
I want my dev VMs to be deallocated outside office hours,
So that we do not pay for idle compute.

Given a VM tagged schedule-profile=weekday-0800-2000 and currently Running
When  a reconciliation cycle runs on Friday at 20:05 in the profile timezone
Then  the VM deallocate operation is submitted
And   an audit record with action=stop and result=submitted is written

Priority: Must
```

### US-02 Temporary override for a release

```
As a workload owner,
I want to keep my UAT environment running late tonight,
So that the release test can finish.

Given resources tagged schedule-override-until=<today 23:00 with offset>
When  cycles run between 20:00 and 23:00
Then  the resources are not stopped
And   the first cycle after 23:00 stops them

Priority: Must
```

### US-03 Dependency-ordered start

```
As a workload owner,
I want my database to be started before my AKS cluster,
So that applications start without connection errors.

Given a PostgreSQL Flexible Server (order 1) and an AKS cluster (order 2) on the same profile
And   the profile defines startOffsetMinutesByOrder {"1": -30, "2": -15}
When  the cycle runs at 07:30
Then  only the database start is submitted
And   the AKS start is submitted in the 07:45 cycle

Priority: Should
```

### US-04 Platform safety

```
As the platform team,
I want platform resources never to be touched,
So that the hub network and shared services stay available.

Given an Azure Firewall in the Connectivity subscription tagged schedule-profile=weekday-0800-2000
When  any reconciliation or on-demand run executes
Then  no action is submitted for the firewall
And   a warning "excluded scope/type" is logged

Priority: Must
```

### US-05 Change a schedule

```
As the platform team,
I want to change a profile's stop time from 20:00 to 19:00,
So that we save more cost.

Given the profile JSON is updated and terraform apply completes
When  the next cycle runs after 19:00
Then  resources on that profile are stopped
And   no function code redeployment was required

Priority: Must
```

### US-06 On-demand start (dry-run)

```
As an operator,
I want to preview which resources would start in a resource group,
So that I can verify scope before acting.

Given I call POST /api/run with action=start, scope=<RG ID>, dryRun=true and a valid Entra token
When  the request is processed
Then  the response lists the resources that would be started
And   no ARM write operation is performed

Priority: Should
```

## 15. Assumptions and Dependencies

| ID | Assumption / dependency |
|---|---|
| A-01 | The deployer has Owner (or Contributor + User Access Administrator) on the Management subscription. |
| A-02 | The deployer can create custom role definitions and role assignments at the in-scope management groups. |
| A-03 | Flex Consumption plan is available in the chosen region. If not, an Elastic Premium (EP1) plan is used as a fallback. |
| A-04 | A central Log Analytics workspace exists in the Management subscription (optional; otherwise one is created). |
| A-05 | Workload owners are responsible for tagging their resources with valid profiles. |
| A-06 | Azure Policy for tag inheritance and allowed values will be delivered as a separate governance work item. |
| A-07 | Outbound access from the Function App to Azure Resource Manager (`management.azure.com`) and Microsoft Entra ID is permitted (through the hub firewall if VNet-integrated). |

## 16. Risks

| ID | Risk | Impact | Likelihood | Mitigation |
|---|---|---|---|---|
| R-01 | Mis-scoped role assignment allows stopping platform resources | High | Low | MG-scoped assignment, exclude list, type deny list, code review |
| R-02 | Resources not started in time for business hours (AKS start takes 5–10 min) | Medium | Medium | Start offsets per order, alert on failed starts |
| R-03 | ARM throttling in large estates | Medium | Low | Resource Graph discovery, bounded parallelism, back-off |
| R-04 | Applications fail after restart due to dependency order | Medium | Medium | `schedule-order`, offsets, owner testing during pilot |
| R-05 | Stopping RI-covered resources gives no saving | Low | Medium | BR-006, FinOps report |
| R-06 | Wrong timezone or holiday data | Medium | Low | Unit tests, dry-run pilot, review of calendars |
| R-07 | AKS stopped beyond the platform's maximum stopped duration | High | Very low | Alert on clusters stopped longer than 30 days |

## 17. Open Issues and Gaps

| ID | Issue | Owner | Status |
|---|---|---|---|
| OI-01 | ⚠️ GAP: Confirm the list of in-scope management groups and any subscriptions to exclude. | Platform Team | Open |
| OI-02 | ⚠️ GAP: Confirm the standard schedule profiles (names, windows, timezones) and the holiday calendar source. | Platform Team / FinOps | Open |
| OI-03 | ⚠️ GAP: Should on-demand start/stop set an automatic override (e.g. 4 hours), or only act once? | Platform Team | Open |
| OI-04 | ⚠️ GAP: Are HA-enabled databases and SQL MI in scope for phase 1? | Workload Owners | Open |
| OI-05 | ⚠️ GAP: Should the HTTP on-demand endpoint be reachable only privately (via hub) or publicly with Entra ID auth? | Security | Open |
| OI-06 | ⚠️ GAP: Is a production opt-in (BR-003) needed in phase 1, or is prod fully excluded? | Governance | Open |
| OI-07 | Decision: Python 3.11 is selected as the function runtime (testability, Azure SDK coverage). PowerShell 7.4 remains an alternative if the operations team prefers it. | Platform Team | Proposed |

## 18. Glossary

| Term | Definition |
|---|---|
| Reconciliation | Comparing the desired state with the actual state and acting only on differences |
| Profile | Named schedule definition (run windows, timezone, holidays) |
| Desired state | `Running` or `Stopped`, computed from the profile at a point in time |
| Flex Consumption | Azure Functions hosting plan with per-execution billing and VNet support |
| NCRONTAB | Six-field CRON format (including seconds) used by Azure Functions timer triggers |
| Resource Graph | Azure service for querying resources across subscriptions and management groups |
| LRO | Long-running operation; an ARM request that completes asynchronously |
| MG | Management group |
