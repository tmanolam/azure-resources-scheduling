# Inputs for the demo landing zone (Plan A — four subscriptions).
#
# Fill these in demo/landing-zone/terraform.tfvars once the subscriptions exist
# (DM-03). The real terraform.tfvars is gitignored; only the .example is committed.

variable "management_subscription_id" {
  type        = string
  description = "sub-demo-management — hosts the scheduler and demo state (MG: demo-platform-management)."
}

variable "workload_dev_subscription_id" {
  type        = string
  description = "sub-demo-workload-dev — non-production workloads (MG: demo-workload-np)."
}

variable "workload_prod_subscription_id" {
  type        = string
  description = "sub-demo-workload-prod — production, proves the hard exclusion (MG: demo-workload-prod)."
}

variable "sandbox_subscription_id" {
  type        = string
  default     = ""
  description = <<-EOT
    sub-demo-sandbox — subscription-level tag inheritance + nested-MG exclusion
    (MG: demo-sandbox). May be empty on first apply if the subscription is not
    created yet (Azure quota); set it and re-apply once it exists. When empty,
    the sandbox subscription placement and tags are skipped (count = 0).
  EOT
}

variable "mg_prefix" {
  type        = string
  default     = "demo"
  description = "Prefix / name of the intermediate root management group (role_assignable_scope)."
}

variable "budget_contact_emails" {
  type        = list(string)
  default     = []
  description = "Email recipients for the budget threshold alerts (DM-13, USD 250/500/750)."
}
