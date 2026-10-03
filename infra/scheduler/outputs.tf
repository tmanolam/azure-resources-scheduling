output "function_app_name" {
  value       = module.function_app.function_app_name
  description = "Function App name (used by the code publish step)."
}

output "resource_group_name" {
  value       = azurerm_resource_group.this.name
  description = "Resource group holding the scheduler."
}

output "app_configuration_endpoint" {
  value       = module.app_config.endpoint
  description = "App Configuration data-plane endpoint."
}

output "managed_identity_principal_id" {
  value       = azurerm_user_assigned_identity.this.principal_id
  description = "Principal ID of the user-assigned managed identity."
}

output "application_insights_name" {
  value       = module.monitoring.application_insights_name
  description = "Application Insights resource name."
}
