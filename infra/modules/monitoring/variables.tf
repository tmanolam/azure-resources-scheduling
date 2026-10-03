variable "resource_group_name" {
  type        = string
  description = "Resource group for monitoring resources."
}

variable "location" {
  type        = string
  description = "Azure region."
}

variable "app_insights_name" {
  type        = string
  description = "Application Insights resource name (e.g. appi-pwrsched)."
}

variable "workspace_name" {
  type        = string
  description = "Name for the Log Analytics workspace created when none is supplied."
}

variable "log_analytics_workspace_id" {
  type        = string
  default     = ""
  description = "Existing central Log Analytics workspace ID; empty creates one (A-04)."
}

variable "action_group_name" {
  type        = string
  description = "Action group name (e.g. ag-pwrsched)."
}

variable "alert_prefix" {
  type        = string
  description = "Prefix for alert rule names (e.g. pwrsched)."
}

variable "alert_email_addresses" {
  type        = list(string)
  default     = []
  description = "Email recipients for alerts (OBS-003/004/005)."
}

variable "tags" {
  type        = map(string)
  default     = {}
  description = "Standard resource tags (IAC-006)."
}
