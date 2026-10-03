output "role_definition_id" {
  value       = azurerm_role_definition.operator.role_definition_resource_id
  description = "Resource ID of the custom role definition."
}

output "assignment_scopes" {
  value       = var.in_scope_management_group_ids
  description = "Management group scopes the role was assigned at."
}
