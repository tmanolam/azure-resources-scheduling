# Inputs for demo/workloads. Fill demo/workloads/terraform.tfvars once the
# subscriptions exist (gitignored; only the .example is committed).

variable "workload_dev_subscription_id" {
  type        = string
  description = "sub-demo-workload-dev — hosts non-production workloads (and all non-prod under Plan B)."
}

variable "workload_prod_subscription_id" {
  type        = string
  description = "sub-demo-workload-prod — hosts only W9 (production exclusion proof)."
}

variable "management_subscription_id" {
  type        = string
  description = "sub-demo-management — hosts only W11 (platform-MG exclusion proof). Ignored under Plan B."
}

variable "sandbox_subscription_id" {
  type        = string
  default     = ""
  description = <<-EOT
    sub-demo-sandbox — hosts W10 (subscription-level tag inheritance, S3). May be
    empty until the subscription is created (Azure quota); when empty, W10 and the
    sandbox network are skipped. Under Plan B, W10 falls back to the dev
    subscription with an RG-level profile tag instead (DM-22).
  EOT
}

variable "plan_b" {
  type        = bool
  default     = false
  description = <<-EOT
    DM-22. false = Plan A (dev/prod/management subscriptions). true = Plan B:
    all non-prod workloads (incl. W11) go into the dev subscription using
    resource groups; only W9 stays in the prod subscription.
  EOT
}

variable "location" {
  type        = string
  default     = "southeastasia"
  description = "Azure region for all demo workloads (matches the profiles' Asia/Bangkok timezone)."
}

variable "vm_size" {
  type        = string
  default     = "Standard_B1s"
  description = "Size for the demo VMs (W1–W6, W9–W11). Burstable to stay in budget."
}

variable "admin_username" {
  type        = string
  default     = "demoadmin"
  description = "Local admin username for the demo VMs. No password; SSH key only (and no inbound anyway)."
}

# --- Standard tags applied by workload owners (the opt-in) -------------------

variable "standard_profile" {
  type        = string
  default     = "weekday-0830-1730"
  description = "The standard schedule profile name tagged on most workloads (D-02)."
}

# --- Optional component toggles (DM-21, §4.2) --------------------------------

variable "enable_aks" {
  type        = bool
  default     = false
  description = "W12 — AKS Free tier, 1 system node Standard_B2s."
}

variable "enable_appgw" {
  type        = bool
  default     = false
  description = "W13 — Application Gateway Standard_v2, fixed capacity 1."
}

variable "enable_sqlmi" {
  type        = bool
  default     = false
  description = "W14 — SQL Managed Instance, General Purpose 4 vCores. Create last; destroy after S17."
}
