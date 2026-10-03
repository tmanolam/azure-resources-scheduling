output "application_insights_name" {
  value       = azurerm_application_insights.this.name
  description = "Application Insights resource name."
}

output "application_insights_connection_string" {
  value       = azurerm_application_insights.this.connection_string
  description = "Connection string for the Functions runtime."
  sensitive   = true
}

output "log_analytics_workspace_id" {
  value       = local.workspace_id
  description = "Workspace ID in use (existing or newly created)."
}

output "action_group_id" {
  value       = azurerm_monitor_action_group.this.id
  description = "Action group resource ID."
}
