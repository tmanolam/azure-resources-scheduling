terraform {
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.0"
    }
  }
}

# --- Runtime storage account (SEC-005) --------------------------------------
resource "azurerm_storage_account" "this" {
  name                     = var.storage_account_name
  resource_group_name      = var.resource_group_name
  location                 = var.location
  account_tier             = "Standard"
  account_replication_type = "LRS"

  min_tls_version                 = "TLS1_2" # SEC-005
  shared_access_key_enabled       = false    # SEC-001/SEC-005: no account keys
  allow_nested_items_to_be_public = false    # SEC-005: no public blob
  public_network_access_enabled   = var.enable_private_networking ? false : true

  tags = var.tags
}

# Deployment package / runtime container used by Flex Consumption.
resource "azurerm_storage_container" "deployments" {
  name                  = "deployments"
  storage_account_id    = azurerm_storage_account.this.id
  container_access_type = "private"
}

# The identity needs data-plane access to the runtime storage (SEC-004),
# because shared-key access is disabled.
resource "azurerm_role_assignment" "identity_blob_owner" {
  scope                = azurerm_storage_account.this.id
  role_definition_name = "Storage Blob Data Owner"
  principal_id         = var.identity_principal_id
}

# --- Flex Consumption plan (D-01, A-03) -------------------------------------
resource "azurerm_service_plan" "this" {
  name                = var.plan_name
  resource_group_name = var.resource_group_name
  location            = var.location
  os_type             = "Linux"
  sku_name            = "FC1" # Flex Consumption
  tags                = var.tags
}

# --- Function App (Flex Consumption, Linux, Python 3.11) --------------------
resource "azurerm_function_app_flex_consumption" "this" {
  name                = var.function_app_name
  resource_group_name = var.resource_group_name
  location            = var.location
  service_plan_id     = azurerm_service_plan.this.id

  storage_container_type            = "blobContainer"
  storage_container_endpoint        = "${azurerm_storage_account.this.primary_blob_endpoint}${azurerm_storage_container.deployments.name}"
  storage_authentication_type       = "UserAssignedIdentity" # SEC-001: no keys
  storage_user_assigned_identity_id = var.identity_id

  runtime_name    = "python"
  runtime_version = "3.11"

  maximum_instance_count = 40
  instance_memory_in_mb  = 2048

  https_only                    = true # SEC-006
  public_network_access_enabled = var.enable_private_networking ? false : true
  enabled                       = var.scheduler_enabled

  virtual_network_subnet_id = var.enable_private_networking ? var.integration_subnet_id : null

  identity {
    type         = "UserAssigned"
    identity_ids = [var.identity_id]
  }

  app_settings = {
    # Auth: no secrets. The worker uses the user-assigned identity (SEC-001).
    "AZURE_CLIENT_ID"          = var.identity_client_id
    "APP_CONFIG_ENDPOINT"      = var.app_config_endpoint
    "RECONCILE_SCHEDULE"       = var.reconcile_schedule
    "FUNCTIONS_WORKER_RUNTIME" = "python"
  }

  site_config {
    minimum_tls_version                    = "1.2" # SEC-006
    application_insights_connection_string = var.app_insights_connection_string
  }

  tags = var.tags
}
