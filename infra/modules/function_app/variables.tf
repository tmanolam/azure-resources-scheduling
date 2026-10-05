variable "resource_group_name" {
  type        = string
  description = "Resource group for the Function App and its storage."
}

variable "location" {
  type        = string
  description = "Azure region."
}

variable "function_app_name" {
  type        = string
  description = "Function App name (e.g. func-pwrsched)."
}

variable "plan_name" {
  type        = string
  description = "Flex Consumption plan name."
}

variable "storage_account_name" {
  type        = string
  description = "Runtime storage account name (3-24 lowercase alphanumerics)."
}

variable "identity_id" {
  type        = string
  description = "Resource ID of the user-assigned managed identity (SEC-001)."
}

variable "identity_client_id" {
  type        = string
  description = "Client ID of the user-assigned managed identity (for AZURE_CLIENT_ID / storage auth)."
}

variable "identity_principal_id" {
  type        = string
  description = "Principal (object) ID of the user-assigned managed identity, for the storage data-plane role assignment (SEC-004)."
}

variable "deployer_object_id" {
  type        = string
  description = "Object ID of the principal running Terraform. Granted data-plane roles on the runtime storage account so refresh/plan/apply can read it with shared keys disabled (SEC-005, DP-01 follow-up)."
}

variable "app_config_endpoint" {
  type        = string
  description = "App Configuration data-plane endpoint."
}

variable "app_insights_connection_string" {
  type        = string
  sensitive   = true
  description = "Application Insights connection string."
}

variable "reconcile_schedule" {
  type        = string
  default     = "0 */15 * * * *"
  description = "NCRONTAB timer expression, UTC (FR-001)."
}

variable "scheduler_enabled" {
  type        = bool
  default     = true
  description = "Set false to disable the timer function (Rollback)."
}

variable "enable_private_networking" {
  type        = bool
  default     = false
  description = "Enable VNet integration + private endpoints (SEC-007)."
}

variable "integration_subnet_id" {
  type        = string
  default     = null
  description = "Delegated subnet for VNet integration when private networking is enabled."
}

variable "tags" {
  type        = map(string)
  default     = {}
  description = "Standard resource tags (IAC-006)."
}
