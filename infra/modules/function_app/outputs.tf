output "function_app_name" {
  value       = azurerm_function_app_flex_consumption.this.name
  description = "Function App name."
}

output "function_app_id" {
  value       = azurerm_function_app_flex_consumption.this.id
  description = "Function App resource ID."
}

output "default_hostname" {
  value       = azurerm_function_app_flex_consumption.this.default_hostname
  description = "Default hostname of the Function App."
}

output "storage_account_name" {
  value       = azurerm_storage_account.this.name
  description = "Runtime storage account name."
}
