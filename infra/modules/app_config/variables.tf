variable "name" {
  type        = string
  description = "Name of the App Configuration store (e.g. appcs-pwrsched)."
}

variable "resource_group_name" {
  type        = string
  description = "Resource group that holds the App Configuration store."
}

variable "location" {
  type        = string
  description = "Azure region."
}

variable "identity_principal_id" {
  type        = string
  description = "Principal ID of the Function App's user-assigned managed identity (granted Data Reader, SEC-004)."
}

variable "deployer_object_id" {
  type        = string
  description = "Object ID of the Terraform deployer, granted App Configuration Data Owner so Terraform can write keys over the data plane."
}

variable "config_root" {
  type        = string
  description = "Absolute path to the repo config/ directory containing settings.json and profiles/."
}

variable "settings" {
  type = object({
    enabled_resource_types = list(string)
    include_scopes         = list(string)
    exclude_scopes         = list(string)
    dry_run                = bool
    max_actions_per_run    = number
    reconcile_schedule     = string
  })
  description = "Effective global settings written as App Configuration keys (overrides config/settings.json for environment-specific values)."
}

variable "public_network_access" {
  type        = string
  default     = "Enabled"
  description = "Set to Disabled when using private endpoints (SEC-007)."

  validation {
    condition     = contains(["Enabled", "Disabled"], var.public_network_access)
    error_message = "public_network_access must be Enabled or Disabled."
  }
}

variable "tags" {
  type        = map(string)
  default     = {}
  description = "Standard resource tags (IAC-006)."
}
