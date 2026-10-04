# =============================================================================
# Outputs — NON-SECRET metadata only (DM-23). The generated SSH private key
# (tls_private_key.vm) and DB passwords (random_password.*) are intentionally
# NOT output. They remain in Terraform state and are never surfaced.
# =============================================================================

output "workload_resource_groups" {
  description = "Resource group names per workload (for locating resources in the portal / KQL)."
  value = {
    w1_vm        = azurerm_resource_group.w1.name
    w2_mixedcase = azurerm_resource_group.w2.name
    w3_override  = azurerm_resource_group.w3.name
    w4_optout    = azurerm_resource_group.w4.name
    w5_poweroff  = azurerm_resource_group.w5.name
    w6_vmss      = azurerm_resource_group.w6.name
    w7w8_db      = azurerm_resource_group.w7w8.name
    w9_prod      = azurerm_resource_group.w9.name
    w10_sandbox  = local.deploy_w10 ? azurerm_resource_group.w10[0].name : "(skipped: sandbox not deployed)"
    w11_platform = azurerm_resource_group.w11.name
    w12_aks      = var.enable_aks ? azurerm_resource_group.w12[0].name : "(disabled)"
    w13_appgw    = var.enable_appgw ? azurerm_resource_group.w13[0].name : "(disabled)"
    w14_sqlmi    = var.enable_sqlmi ? azurerm_resource_group.w14[0].name : "(disabled)"
  }
}

output "ssh_public_key" {
  description = "The generated SSH PUBLIC key (safe to share). The private key is never output."
  value       = tls_private_key.vm.public_key_openssh
}

output "plan" {
  description = "Which deployment plan is active."
  value       = var.plan_b ? "Plan B (single non-prod subscription)" : "Plan A (dev/prod/management subscriptions)"
}

output "optional_components" {
  description = "State of the W12–W14 toggles."
  value = {
    w12_aks   = var.enable_aks
    w13_appgw = var.enable_appgw
    w14_sqlmi = var.enable_sqlmi
  }
}
