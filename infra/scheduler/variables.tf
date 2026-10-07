variable "subscription_id" {
  type        = string
  description = "Management subscription hosting the single tenant-wide scheduler."
}

variable "location" {
  type        = string
  description = "Azure region."
}

variable "name_suffix" {
  type        = string
  default     = ""
  description = "Optional short suffix appended to resource names (e.g. a region code or a second-instance marker). Leave empty for the standard single deployment. Lowercase alphanumerics recommended."

  validation {
    condition     = can(regex("^[a-z0-9]*$", var.name_suffix)) && length(var.name_suffix) <= 8
    error_message = "name_suffix must be empty or up to 8 lowercase alphanumeric characters."
  }
}

variable "in_scope_management_group_ids" {
  type        = list(string)
  description = "Management groups the single scheduler queries and is assigned the custom role at — typically the tenant's non-production MGs (e.g. Landing Zones, Sandbox) (OI-01)."
}

variable "role_assignable_scope" {
  type        = string
  description = "Intermediate/org management group that is the assignable (parent) scope for the custom role definition (SEC-003)."
}

variable "excluded_scope_ids" {
  type        = list(string)
  default     = []
  description = "MG/subscription/RG IDs always excluded (FR-011). Production is additionally hard-excluded in the engine regardless of this list (BR-003)."
}

variable "enabled_resource_types" {
  type        = list(string)
  default     = ["vm"]
  description = "Handler keys to enable (FR-012, SEC-002)."
}

variable "reconcile_schedule" {
  type        = string
  default     = "0 */15 * * * *"
  description = "NCRONTAB expression, UTC (FR-001)."
}

variable "scheduler_enabled" {
  type        = bool
  default     = true
  description = "Set false to disable the timer function."
}

variable "dry_run" {
  type        = bool
  default     = true
  description = "Global dry-run switch (FR-030). Keep true until verified."
}

variable "max_actions_per_run" {
  type        = number
  default     = 200
  description = "Safety cap per cycle (FR-031). Single combined start/stop cap (D-09). Size from the measured peak transition (SC-03, ~= peak x 1.2)."
}

variable "max_parallel_actions" {
  type        = number
  default     = 10
  description = "Bound on parallel start/stop submissions per order group (SC-01, FR-034). Submission is parallel within an order group with a barrier between groups, so dependency ordering is preserved."

  validation {
    condition     = var.max_parallel_actions >= 1 && var.max_parallel_actions <= 100
    error_message = "max_parallel_actions must be between 1 and 100 (10-20 is a sensible range; very high values risk per-subscription ARM write throttling)."
  }
}

variable "log_converged_decisions" {
  type        = bool
  default     = true
  description = "Emit a per-resource decision record for already-converged (no-op) resources (SC-04, NFR-011). Set false above ~1,000 in-scope resources to keep Application Insights ingestion proportional to actions, not resources; summary counts still carry converged/desiredRunning/desiredStopped."
}

variable "log_analytics_workspace_id" {
  type        = string
  default     = ""
  description = "Existing central workspace; empty creates one (A-04)."
}

variable "enable_private_networking" {
  type        = bool
  default     = false
  description = "Private endpoints + VNet integration (SEC-007). NOT IMPLEMENTED in phase 1: setting true only disables public access without creating private endpoints or DNS, which breaks the deployment. Rejected by validation until private endpoints land."

  validation {
    # Finding H5: enabling private networking currently disables public access
    # on Storage and App Configuration but creates no private endpoints or
    # private DNS, so the Function App cannot reach storage (won't start) and
    # Terraform cannot write App Configuration keys. Fail fast with a clear
    # message rather than producing a broken deployment.
    condition     = var.enable_private_networking == false
    error_message = "enable_private_networking is not supported yet: it would disable public access without provisioning private endpoints or DNS, breaking the Function App and Terraform's App Configuration writes (finding H5). Keep it false until private endpoints are implemented."
  }
}

variable "integration_subnet_id" {
  type        = string
  default     = null
  description = "Subnet for VNet integration when private."
}

variable "alert_email_addresses" {
  type        = list(string)
  default     = []
  description = "Alert recipients (OBS-003/004/005)."
}

variable "tags" {
  type        = map(string)
  description = "Standard resource tags (IAC-006)."
}

variable "operator_object_id" {
  type        = string
  default     = ""
  description = <<-EOT
    DP-06: Entra object ID (an operators *group* is recommended, or a user) that
    receives the data-plane role assignments the deployer needs — App
    Configuration Data Owner, and Storage Blob Data Owner + Queue/Table Data
    Contributor on the runtime storage account. These let Terraform read/write
    App Configuration keys and the runtime storage account during apply.

    Leave empty to default to the identity currently running Terraform
    (data.azurerm_client_config.current.object_id). Setting it to a stable
    operators group means a different person or CI identity can run plan/apply
    without replacing these assignments (which would otherwise churn the plan,
    breaking the VERIFICATION §4 go-live checkpoint, and revoke the previous
    deployer's data-plane access). Use a group's object ID for best results.
  EOT
}
