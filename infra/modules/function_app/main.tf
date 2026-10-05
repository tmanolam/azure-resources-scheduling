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
# Created over the data plane (shared keys disabled, SEC-005), so it needs the
# deployer's Storage Blob Data Owner role to exist first (DP-01 follow-up).
resource "azurerm_storage_container" "deployments" {
  name                  = "deployments"
  storage_account_id    = azurerm_storage_account.this.id
  container_access_type = "private"

  depends_on = [azurerm_role_assignment.deployer_blob_owner]
}

# The identity needs data-plane access to the runtime storage (SEC-004),
# because shared-key access is disabled.
resource "azurerm_role_assignment" "identity_blob_owner" {
  scope                = azurerm_storage_account.this.id
  role_definition_name = "Storage Blob Data Owner"
  principal_id         = var.identity_principal_id
  principal_type       = "ServicePrincipal" # L2: avoid propagation races on a new identity
}

# The Functions host's identity-based AzureWebJobsStorage connection (M4) uses
# queues for the timer singleton lease and tables for the schedule monitor
# (use_monitor=True), so the identity also needs queue and table data roles.
resource "azurerm_role_assignment" "identity_queue_contributor" {
  scope                = azurerm_storage_account.this.id
  role_definition_name = "Storage Queue Data Contributor"
  principal_id         = var.identity_principal_id
  principal_type       = "ServicePrincipal"
}

resource "azurerm_role_assignment" "identity_table_contributor" {
  scope                = azurerm_storage_account.this.id
  role_definition_name = "Storage Table Data Contributor"
  principal_id         = var.identity_principal_id
  principal_type       = "ServicePrincipal"
}

# DP-01 follow-up: the deployer (the principal running Terraform) also needs
# data-plane roles on the runtime storage account. With shared keys disabled
# (SEC-005) and storage_use_azuread=true, the azurerm provider reads blob,
# queue and table properties over the data plane during refresh/plan/apply; a
# deployer without these roles gets 403 KeyBasedAuthenticationNotPermitted (and
# the operator previously had to grant them by hand). Granting them in
# Terraform — mirroring the App Configuration Data Owner grant for the deployer
# — makes the first apply self-sufficient on the runtime SA.
resource "azurerm_role_assignment" "deployer_blob_owner" {
  scope                = azurerm_storage_account.this.id
  role_definition_name = "Storage Blob Data Owner"
  principal_id         = var.deployer_object_id
}

resource "azurerm_role_assignment" "deployer_queue_contributor" {
  scope                = azurerm_storage_account.this.id
  role_definition_name = "Storage Queue Data Contributor"
  principal_id         = var.deployer_object_id
}

resource "azurerm_role_assignment" "deployer_table_contributor" {
  scope                = azurerm_storage_account.this.id
  role_definition_name = "Storage Table Data Contributor"
  principal_id         = var.deployer_object_id
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
    "AZURE_CLIENT_ID"     = var.identity_client_id
    "APP_CONFIG_ENDPOINT" = var.app_config_endpoint
    "RECONCILE_SCHEDULE"  = var.reconcile_schedule
    # Note: FUNCTIONS_WORKER_RUNTIME must NOT be set as an app setting on Flex
    # Consumption sites (the platform rejects it with BadRequest 51021); the
    # runtime is configured via runtime_name/runtime_version above.
    #
    # DP-05: APPLICATIONINSIGHTS_CONNECTION_STRING is intentionally NOT set here.
    # Telemetry export to Application Insights (H1) is configured via
    # site_config.application_insights_connection_string below. Azure echoes
    # that value into app_settings, so declaring it in both places made every
    # `terraform plan` show "1 to change" on the Function App forever, breaking
    # IAC-008 and the VERIFICATION §4 go-live checkpoint ("the plan's only
    # change is pwrsched:dryRun"). Keeping it only in site_config leaves the
    # plan clean.

    # Host storage for the timer singleton lease and schedule monitor
    # (use_monitor=True / IsPastDue recovery). With shared keys disabled this
    # must be an identity-based connection, not a connection string (M4,
    # FR-007, NFR-004, SEC-001).
    "AzureWebJobsStorage__accountName" = azurerm_storage_account.this.name
    "AzureWebJobsStorage__credential"  = "managedidentity"
    "AzureWebJobsStorage__clientId"    = var.identity_client_id

    # DP-04: pin the bare `AzureWebJobsStorage` setting to an empty string.
    # The azurerm provider re-injects a key-based connection string even in
    # identity mode (hashicorp/terraform-provider-azurerm#29149). With shared
    # keys disabled (SEC-005) that injected setting is a dead, key-based
    # connection that OVERRIDES the identity-based `AzureWebJobsStorage__*`
    # settings above: the host then fails to acquire the timer singleton lease
    # and drains with storage auth 403s. Declaring it empty here makes
    # Terraform own the key and assert the empty value on every apply, so the
    # poisoned connection can never be reintroduced (replaces the earlier
    # one-off `az` runtime workaround).
    "AzureWebJobsStorage" = ""
  }

  site_config {
    minimum_tls_version                    = "1.2" # SEC-006
    application_insights_connection_string = var.app_insights_connection_string
  }

  tags = var.tags
}
