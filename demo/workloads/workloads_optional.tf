# =============================================================================
# DM-21 — Optional workloads W12–W14 (DEMO_TENANT_PLAN §4.2). Each is gated by
# its enable_* toggle (default false) and lives in the dev subscription.
# Tagged Standard; default order comes from the handler (AKS/AppGw = 2, MI = 1).
# =============================================================================

# --- W12 — AKS, Free tier, 1 system node Standard_B2s ------------------------
resource "azurerm_resource_group" "w12" {
  count    = var.enable_aks ? 1 : 0
  provider = azurerm.dev
  name     = "rg-demo-aks"
  location = var.location
  tags     = { "schedule-profile" = var.standard_profile }
}

resource "azurerm_kubernetes_cluster" "w12" {
  count               = var.enable_aks ? 1 : 0
  provider            = azurerm.dev
  name                = "aks-demo-w12"
  resource_group_name = azurerm_resource_group.w12[0].name
  location            = var.location
  dns_prefix          = "demo-w12"
  sku_tier            = "Free"

  # Explicit node resource group name so scenario S18 (V1 / HR-007) can tag it
  # and prove AKS-managed node pool scale sets are never acted on directly.
  # (Default would be an auto-generated MC_<rg>_<cluster>_<region> name.)
  node_resource_group = "rg-demo-aks-nodes"

  default_node_pool {
    name       = "system"
    node_count = 1
    vm_size    = "Standard_B2s"
  }

  identity {
    type = "SystemAssigned"
  }

  tags = { "schedule-profile" = var.standard_profile }
}

# --- W13 — Application Gateway Standard_v2, fixed capacity 1 -----------------
resource "azurerm_resource_group" "w13" {
  count    = var.enable_appgw ? 1 : 0
  provider = azurerm.dev
  name     = "rg-demo-appgw"
  location = var.location
  tags     = { "schedule-profile" = var.standard_profile }
}

# App Gateway needs its own dedicated subnet. Carve one from the dev VNet.
resource "azurerm_subnet" "appgw" {
  count                = var.enable_appgw ? 1 : 0
  provider             = azurerm.dev
  name                 = "snet-appgw"
  resource_group_name  = azurerm_resource_group.net_dev.name
  virtual_network_name = azurerm_virtual_network.dev.name
  address_prefixes     = ["10.10.3.0/24"]
}

# App Gateway v2 requires a public IP for its frontend. This carries no inbound
# NSG allow rules on a workload (the gateway itself needs the PIP to exist);
# the gateway has no backends, it exists only to be started/stopped (DM-23: the
# VMs have no public inbound; the App Gateway PIP is a gateway requirement).
resource "azurerm_public_ip" "appgw" {
  count               = var.enable_appgw ? 1 : 0
  provider            = azurerm.dev
  name                = "pip-demo-w13"
  resource_group_name = azurerm_resource_group.w13[0].name
  location            = var.location
  allocation_method   = "Static"
  sku                 = "Standard"
}

resource "azurerm_application_gateway" "w13" {
  count               = var.enable_appgw ? 1 : 0
  provider            = azurerm.dev
  name                = "appgw-demo-w13"
  resource_group_name = azurerm_resource_group.w13[0].name
  location            = var.location
  tags                = { "schedule-profile" = var.standard_profile }

  sku {
    name     = "Standard_v2"
    tier     = "Standard_v2"
    capacity = 1
  }

  gateway_ip_configuration {
    name      = "gwipconfig"
    subnet_id = azurerm_subnet.appgw[0].id
  }

  frontend_port {
    name = "port80"
    port = 80
  }

  frontend_ip_configuration {
    name                 = "frontend"
    public_ip_address_id = azurerm_public_ip.appgw[0].id
  }

  backend_address_pool {
    name = "empty-pool"
  }

  backend_http_settings {
    name                  = "http"
    cookie_based_affinity = "Disabled"
    port                  = 80
    protocol              = "Http"
    request_timeout       = 20
  }

  http_listener {
    name                           = "listener"
    frontend_ip_configuration_name = "frontend"
    frontend_port_name             = "port80"
    protocol                       = "Http"
  }

  request_routing_rule {
    name                       = "rule"
    rule_type                  = "Basic"
    http_listener_name         = "listener"
    backend_address_pool_name  = "empty-pool"
    backend_http_settings_name = "http"
    priority                   = 100
  }
}

# --- W14 — SQL Managed Instance, General Purpose, 4 vCores ------------------
# Create LAST (after T-602) and destroy after scenario S17 (budget, §4.3).
# Needs the delegated subnet from network.tf (snet-sqlmi) and an NSG/route table.
resource "azurerm_resource_group" "w14" {
  count    = var.enable_sqlmi ? 1 : 0
  provider = azurerm.dev
  name     = "rg-demo-sqlmi"
  location = var.location
  tags     = { "schedule-profile" = var.standard_profile }
}

resource "azurerm_network_security_group" "sqlmi" {
  count               = var.enable_sqlmi ? 1 : 0
  provider            = azurerm.dev
  name                = "nsg-demo-sqlmi"
  resource_group_name = azurerm_resource_group.w14[0].name
  location            = var.location
}

resource "azurerm_route_table" "sqlmi" {
  count               = var.enable_sqlmi ? 1 : 0
  provider            = azurerm.dev
  name                = "rt-demo-sqlmi"
  resource_group_name = azurerm_resource_group.w14[0].name
  location            = var.location
}

resource "azurerm_subnet_network_security_group_association" "sqlmi" {
  count                     = var.enable_sqlmi ? 1 : 0
  provider                  = azurerm.dev
  subnet_id                 = azurerm_subnet.sqlmi[0].id
  network_security_group_id = azurerm_network_security_group.sqlmi[0].id
}

resource "azurerm_subnet_route_table_association" "sqlmi" {
  count          = var.enable_sqlmi ? 1 : 0
  provider       = azurerm.dev
  subnet_id      = azurerm_subnet.sqlmi[0].id
  route_table_id = azurerm_route_table.sqlmi[0].id
}

resource "azurerm_mssql_managed_instance" "w14" {
  count               = var.enable_sqlmi ? 1 : 0
  provider            = azurerm.dev
  name                = "sqlmi-demo-w14"
  resource_group_name = azurerm_resource_group.w14[0].name
  location            = var.location

  administrator_login          = "demomi"
  administrator_login_password = random_password.postgres.result # reuse the generated secret; never output

  license_type       = "BasePrice"
  sku_name           = "GP_Gen5"
  vcores             = 4
  storage_size_in_gb = 32
  subnet_id          = azurerm_subnet.sqlmi[0].id

  tags = { "schedule-profile" = var.standard_profile }

  depends_on = [
    azurerm_subnet_network_security_group_association.sqlmi,
    azurerm_subnet_route_table_association.sqlmi,
  ]
}
