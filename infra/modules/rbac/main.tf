terraform {
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.0"
    }
  }
}

locals {
  # Base read permissions always required (§11.1).
  base_actions = [
    "Microsoft.Resources/subscriptions/resourceGroups/read",
    "Microsoft.ResourceGraph/resources/read",
  ]

  # Per-handler action sets (§11.1). Only enabled types contribute actions
  # (SEC-002: least privilege).
  actions_by_handler = {
    vm = [
      "Microsoft.Compute/virtualMachines/read",
      "Microsoft.Compute/virtualMachines/instanceView/read",
      "Microsoft.Compute/virtualMachines/start/action",
      "Microsoft.Compute/virtualMachines/deallocate/action",
    ]
    vmss = [
      "Microsoft.Compute/virtualMachineScaleSets/read",
      "Microsoft.Compute/virtualMachineScaleSets/start/action",
      "Microsoft.Compute/virtualMachineScaleSets/deallocate/action",
    ]
    aks = [
      "Microsoft.ContainerService/managedClusters/read",
      "Microsoft.ContainerService/managedClusters/start/action",
      "Microsoft.ContainerService/managedClusters/stop/action",
    ]
    "postgres-flex" = [
      "Microsoft.DBforPostgreSQL/flexibleServers/read",
      "Microsoft.DBforPostgreSQL/flexibleServers/start/action",
      "Microsoft.DBforPostgreSQL/flexibleServers/stop/action",
    ]
    "mysql-flex" = [
      "Microsoft.DBforMySQL/flexibleServers/read",
      "Microsoft.DBforMySQL/flexibleServers/start/action",
      "Microsoft.DBforMySQL/flexibleServers/stop/action",
    ]
    sqlmi = [
      "Microsoft.Sql/managedInstances/read",
      "Microsoft.Sql/managedInstances/start/action",
      "Microsoft.Sql/managedInstances/stop/action",
    ]
    appgw = [
      "Microsoft.Network/applicationGateways/read",
      "Microsoft.Network/applicationGateways/start/action",
      "Microsoft.Network/applicationGateways/stop/action",
    ]
  }

  # Flatten enabled handlers' actions + base, de-duplicated.
  enabled_actions = flatten([
    for k in var.enabled_resource_types : lookup(local.actions_by_handler, k, [])
  ])
  all_actions = distinct(concat(local.base_actions, local.enabled_actions))
}

# --- Custom role definition "Resource Power Operator" (SEC-002) -------------
resource "azurerm_role_definition" "operator" {
  name        = var.role_name
  scope       = var.role_scope
  description = "Least-privilege start/stop operator for the Resource Power Scheduler. Actions derived from enabled resource types."

  permissions {
    actions          = local.all_actions
    not_actions      = []
    data_actions     = []
    not_data_actions = []
  }

  # Role assignable only within the org/intermediate MG subtree (SEC-003).
  assignable_scopes = [var.role_scope]
}

# --- Assignments at in-scope management groups only (SEC-003) ---------------
resource "azurerm_role_assignment" "mg" {
  for_each           = toset(var.in_scope_management_group_ids)
  scope              = each.value
  role_definition_id = azurerm_role_definition.operator.role_definition_resource_id
  principal_id       = var.identity_principal_id
}
