variable "role_name" {
  type        = string
  description = "Custom role name (e.g. 'Resource Power Operator - dev')."
}

variable "role_scope" {
  type        = string
  description = "Assignable scope for the role definition — the intermediate/org management group that is a parent of all in-scope MGs."
}

variable "in_scope_management_group_ids" {
  type        = list(string)
  description = "Management group IDs where the role is assigned to the identity (SEC-003). Must NOT include Tenant Root, intermediate root or Platform."
}

variable "identity_principal_id" {
  type        = string
  description = "Principal ID of the Function App's user-assigned managed identity."
}

variable "enabled_resource_types" {
  type        = list(string)
  description = "Handler keys enabled; drives which start/stop actions the custom role includes (SEC-002)."
}
