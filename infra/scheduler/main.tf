locals {
  region = var.location

  # Optional suffix appended to names; empty by default for the single tenant
  # deployment. Produces e.g. "func-pwrsched" or "func-pwrsched-sea".
  suffix    = var.name_suffix == "" ? "" : "-${var.name_suffix}"
  suffix_sa = var.name_suffix # storage name has no separators
  base      = "pwrsched"

  # H6: Function App hostnames, storage account names and App Configuration
  # names are globally unique across all of Azure. A short random token keeps
  # them collision-free across tenants (and re-deployments reuse the same token
  # because it is stored in Terraform state).
  rand    = random_string.unique.result
  rand_sa = local.rand # no separator for storage

  rg_name           = "rg-${local.base}${local.suffix}-${local.region}"
  identity_name     = "id-${local.base}${local.suffix}"
  func_name         = "func-${local.base}${local.suffix}-${local.rand}"
  plan_name         = "plan-${local.base}${local.suffix}"
  appcs_name        = "appcs-${local.base}${local.suffix}-${local.rand}"
  appi_name         = "appi-${local.base}${local.suffix}"
  workspace_name    = "log-${local.base}${local.suffix}"
  action_group_name = "ag-${local.base}${local.suffix}"
  storage_name      = "st${local.base}${local.suffix_sa}${local.rand_sa}" # 3-24 lowercase alphanumerics
  role_name         = var.name_suffix == "" ? "Resource Power Operator" : "Resource Power Operator - ${var.name_suffix}"

  # infra/scheduler/ is two levels under the repo root.
  config_root = "${path.module}/../../config"
}

# H6: 4-char lowercase-alphanumeric token making globally unique names unique.
# Kept in state (no keepers) so it is stable across applies for one deployment.
resource "random_string" "unique" {
  length  = 4
  lower   = true
  upper   = false
  numeric = true
  special = false
}

data "azurerm_client_config" "current" {}

locals {
  # DP-06: the identity that owns the deployer data-plane role assignments.
  # Prefer an explicit operators group/user (var.operator_object_id); fall back
  # to whoever is running Terraform so a first deploy still works unconfigured.
  deployer_object_id = var.operator_object_id != "" ? var.operator_object_id : data.azurerm_client_config.current.object_id
}

resource "azurerm_resource_group" "this" {
  name     = local.rg_name
  location = local.region
  tags     = var.tags
}

# User-assigned managed identity used for all Azure access (SEC-001).
resource "azurerm_user_assigned_identity" "this" {
  name                = local.identity_name
  resource_group_name = azurerm_resource_group.this.name
  location            = local.region
  tags                = var.tags
}

module "monitoring" {
  source = "../modules/monitoring"

  resource_group_name        = azurerm_resource_group.this.name
  location                   = local.region
  app_insights_name          = local.appi_name
  workspace_name             = local.workspace_name
  log_analytics_workspace_id = var.log_analytics_workspace_id
  action_group_name          = local.action_group_name
  alert_prefix               = "${local.base}${local.suffix}"
  alert_email_addresses      = var.alert_email_addresses
  tags                       = var.tags
}

module "app_config" {
  source = "../modules/app_config"

  name                  = local.appcs_name
  resource_group_name   = azurerm_resource_group.this.name
  location              = local.region
  identity_principal_id = azurerm_user_assigned_identity.this.principal_id
  deployer_object_id    = local.deployer_object_id
  config_root           = local.config_root
  public_network_access = var.enable_private_networking ? "Disabled" : "Enabled"

  settings = {
    enabled_resource_types  = var.enabled_resource_types
    include_scopes          = var.in_scope_management_group_ids
    exclude_scopes          = var.excluded_scope_ids
    dry_run                 = var.dry_run
    max_actions_per_run     = var.max_actions_per_run
    max_parallel_actions    = var.max_parallel_actions
    log_converged_decisions = var.log_converged_decisions
    reconcile_schedule      = var.reconcile_schedule
  }

  tags = var.tags
}

module "rbac" {
  source = "../modules/rbac"

  role_name                     = local.role_name
  role_scope                    = var.role_assignable_scope
  in_scope_management_group_ids = var.in_scope_management_group_ids
  identity_principal_id         = azurerm_user_assigned_identity.this.principal_id
  enabled_resource_types        = var.enabled_resource_types
  # Reject any in-scope MG that is also an excluded (e.g. Platform) MG (L2).
  platform_management_group_ids = var.excluded_scope_ids
}

module "function_app" {
  source = "../modules/function_app"

  resource_group_name            = azurerm_resource_group.this.name
  location                       = local.region
  function_app_name              = local.func_name
  plan_name                      = local.plan_name
  storage_account_name           = local.storage_name
  identity_id                    = azurerm_user_assigned_identity.this.id
  identity_client_id             = azurerm_user_assigned_identity.this.client_id
  identity_principal_id          = azurerm_user_assigned_identity.this.principal_id
  deployer_object_id             = local.deployer_object_id
  app_config_endpoint            = module.app_config.endpoint
  app_insights_connection_string = module.monitoring.application_insights_connection_string
  reconcile_schedule             = var.reconcile_schedule
  scheduler_enabled              = var.scheduler_enabled
  enable_private_networking      = var.enable_private_networking
  integration_subnet_id          = var.integration_subnet_id
  tags                           = var.tags
}
