terraform {
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.0"
    }
  }
}

# --- App Configuration store (§6) -------------------------------------------
resource "azurerm_app_configuration" "this" {
  name                       = var.name
  resource_group_name        = var.resource_group_name
  location                   = var.location
  sku                        = "standard"
  local_auth_enabled         = false # SEC-001: Entra ID / managed identity only, no access keys
  public_network_access      = var.public_network_access
  purge_protection_enabled   = false
  soft_delete_retention_days = 1

  tags = var.tags
}

# --- Data-plane role assignments --------------------------------------------
# Deployer needs Data Owner to write keys over the data plane (README note).
resource "azurerm_role_assignment" "deployer_data_owner" {
  scope                = azurerm_app_configuration.this.id
  role_definition_name = "App Configuration Data Owner"
  principal_id         = var.deployer_object_id
}

# The Function App identity needs Data Reader to read config at runtime (SEC-004).
resource "azurerm_role_assignment" "identity_data_reader" {
  scope                = azurerm_app_configuration.this.id
  role_definition_name = "App Configuration Data Reader"
  principal_id         = var.identity_principal_id
}

# --- Keys loaded from versioned files (IAC-004) -----------------------------
locals {
  # Profile JSON files -> keys pwrsched:profiles:<name> (§6.2).
  profile_files = fileset("${var.config_root}/profiles", "*.json")
  profiles = {
    for f in local.profile_files :
    trimsuffix(f, ".json") => file("${var.config_root}/profiles/${f}")
  }

  # Global settings keys (§6.3). Environment-specific values come from var.settings
  # so the same config/ files work across dev/prod.
  setting_values = {
    "pwrsched:resourceTypes"     = jsonencode(var.settings.enabled_resource_types)
    "pwrsched:scopes:include"    = jsonencode(var.settings.include_scopes)
    "pwrsched:scopes:exclude"    = jsonencode(var.settings.exclude_scopes)
    "pwrsched:dryRun"            = tostring(var.settings.dry_run)
    "pwrsched:maxActionsPerRun"  = tostring(var.settings.max_actions_per_run)
    "pwrsched:reconcileSchedule" = var.settings.reconcile_schedule
  }
}

resource "azurerm_app_configuration_key" "profiles" {
  for_each               = local.profiles
  configuration_store_id = azurerm_app_configuration.this.id
  key                    = "pwrsched:profiles:${each.key}"
  content_type           = "application/json"
  value                  = each.value

  # Keys are written over the data plane; wait for the deployer role to exist.
  depends_on = [azurerm_role_assignment.deployer_data_owner]
}

resource "azurerm_app_configuration_key" "settings" {
  for_each               = local.setting_values
  configuration_store_id = azurerm_app_configuration.this.id
  key                    = each.key
  value                  = each.value

  depends_on = [azurerm_role_assignment.deployer_data_owner]
}
