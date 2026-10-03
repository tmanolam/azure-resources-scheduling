output "id" {
  value       = azurerm_app_configuration.this.id
  description = "Resource ID of the App Configuration store."
}

output "endpoint" {
  value       = azurerm_app_configuration.this.endpoint
  description = "Data-plane endpoint (e.g. https://appcs-pwrsched.azconfig.io)."
}

output "name" {
  value       = azurerm_app_configuration.this.name
  description = "App Configuration store name."
}
