# =============================================================================
# DM-14 — Outputs: MG and subscription IDs, and the ready-made scope lists for
# infra/scheduler's demo.tfvars (§2.3). The renderer script (render-demo-tfvars.sh)
# consumes these as JSON.
# =============================================================================

output "mg_ids" {
  description = "All management group resource IDs, keyed by short name."
  value = {
    demo                  = azurerm_management_group.demo.id
    platform              = azurerm_management_group.platform.id
    platform_management   = azurerm_management_group.platform_management.id
    platform_connectivity = azurerm_management_group.platform_connectivity.id
    landingzones          = azurerm_management_group.landingzones.id
    workload_np           = azurerm_management_group.workload_np.id
    workload_prod         = azurerm_management_group.workload_prod.id
    sandbox               = azurerm_management_group.sandbox.id
    sandbox_excluded      = azurerm_management_group.sandbox_excluded.id
    decommissioned        = azurerm_management_group.decommissioned.id
  }
}

# --- Values that map directly onto infra/scheduler variables (§2.3) ----------

output "role_assignable_scope" {
  description = "Intermediate root MG — infra/scheduler var.role_assignable_scope."
  value       = azurerm_management_group.demo.id
}

output "in_scope_management_group_ids" {
  description = "In-scope MGs — infra/scheduler var.in_scope_management_group_ids."
  value = [
    azurerm_management_group.landingzones.id,
    azurerm_management_group.sandbox.id,
  ]
}

output "excluded_scope_ids" {
  description = "Excluded scopes (Platform MG + nested sandbox exclude, S9) — var.excluded_scope_ids."
  value = [
    azurerm_management_group.platform.id,
    azurerm_management_group.sandbox_excluded.id,
  ]
}

output "subscription_ids" {
  description = "Demo subscription IDs by role (sandbox omitted when not set)."
  value = merge(
    {
      management    = var.management_subscription_id
      workload_dev  = var.workload_dev_subscription_id
      workload_prod = var.workload_prod_subscription_id
    },
    var.sandbox_subscription_id == "" ? {} : { sandbox = var.sandbox_subscription_id }
  )
}
