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

  validation {
    # SEC-003 / R-01 (L2): never assign the custom role at the Tenant Root
    # Group. Its MG id equals the tenant GUID, i.e. the path ends in a
    # standard UUID. Reject that shape to prevent a tenant-wide assignment.
    condition = alltrue([
      for id in var.in_scope_management_group_ids :
      !can(regex("(?i)/managementGroups/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", id))
    ])
    error_message = "in_scope_management_group_ids must not include the Tenant Root Group (whose id is the tenant GUID). Assign only at non-production child MGs (SEC-003, R-01)."
  }

  validation {
    # Reject any explicitly-listed Platform MG (BR-001): shared platform
    # services must never be scheduled.
    condition = length(setintersection(
      toset(var.in_scope_management_group_ids),
      toset(var.platform_management_group_ids),
    )) == 0
    error_message = "in_scope_management_group_ids must not include any platform_management_group_ids (Platform MG is excluded by BR-001/SEC-003)."
  }
}

variable "platform_management_group_ids" {
  type        = list(string)
  default     = []
  description = "Platform MG IDs that must never appear in in_scope_management_group_ids (BR-001, SEC-003, R-01). Used by validation only."
}

variable "identity_principal_id" {
  type        = string
  description = "Principal ID of the Function App's user-assigned managed identity."
}

variable "enabled_resource_types" {
  type        = list(string)
  description = "Handler keys enabled; drives which start/stop actions the custom role includes (SEC-002)."
}
