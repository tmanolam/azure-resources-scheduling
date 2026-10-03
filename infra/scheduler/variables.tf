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
  description = "Safety cap per cycle (FR-031)."
}

variable "log_analytics_workspace_id" {
  type        = string
  default     = ""
  description = "Existing central workspace; empty creates one (A-04)."
}

variable "enable_private_networking" {
  type        = bool
  default     = false
  description = "Private endpoints + VNet integration (SEC-007)."
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
