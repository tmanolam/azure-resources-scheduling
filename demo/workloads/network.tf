# =============================================================================
# DM-23 — Generated secrets (never output) + per-subscription networking with
# NO public inbound access.
#
# - SSH: a generated key pair; the private key stays in state and is never
#   exposed via outputs. VMs have no public IP and no inbound NSG rule, so SSH
#   is not reachable anyway — the key only satisfies the VM's required admin
#   credential.
# - DB passwords: generated per server, never output.
# =============================================================================

resource "tls_private_key" "vm" {
  algorithm = "RSA"
  rsa_bits  = 4096
}

resource "random_password" "postgres" {
  length           = 24
  special          = true
  override_special = "!#$%*-_"
}

resource "random_password" "mysql" {
  length           = 24
  special          = true
  override_special = "!#$%*-_"
}

# -----------------------------------------------------------------------------
# Networking. One VNet + subnet per subscription that hosts VMs. No public IPs,
# no inbound allow rules. The management network (W11) and prod network (W9) are
# always created; all four subscriptions draw on the credit (plan v0.3).
# -----------------------------------------------------------------------------

# --- Dev network -------------------------------------------------------------
resource "azurerm_resource_group" "net_dev" {
  provider = azurerm.dev
  name     = "rg-demo-network-dev"
  location = var.location
}

resource "azurerm_virtual_network" "dev" {
  provider            = azurerm.dev
  name                = "vnet-demo-dev"
  resource_group_name = azurerm_resource_group.net_dev.name
  location            = var.location
  address_space       = ["10.10.0.0/16"]
}

resource "azurerm_subnet" "dev" {
  provider             = azurerm.dev
  name                 = "snet-workloads"
  resource_group_name  = azurerm_resource_group.net_dev.name
  virtual_network_name = azurerm_virtual_network.dev.name
  address_prefixes     = ["10.10.1.0/24"]
}

resource "azurerm_network_security_group" "dev" {
  provider            = azurerm.dev
  name                = "nsg-demo-dev"
  resource_group_name = azurerm_resource_group.net_dev.name
  location            = var.location
  # No security_rule blocks: default rules deny all inbound from the internet.
}

resource "azurerm_subnet_network_security_group_association" "dev" {
  provider                  = azurerm.dev
  subnet_id                 = azurerm_subnet.dev.id
  network_security_group_id = azurerm_network_security_group.dev.id
}

# Optional delegated subnet for SQL MI (W14), dev subscription.
resource "azurerm_subnet" "sqlmi" {
  count                = var.enable_sqlmi ? 1 : 0
  provider             = azurerm.dev
  name                 = "snet-sqlmi"
  resource_group_name  = azurerm_resource_group.net_dev.name
  virtual_network_name = azurerm_virtual_network.dev.name
  address_prefixes     = ["10.10.2.0/27"]

  delegation {
    name = "managedinstancedelegation"
    service_delegation {
      name    = "Microsoft.Sql/managedInstances"
      actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
    }
  }
}

# --- Prod network (W9 only) --------------------------------------------------
resource "azurerm_resource_group" "net_prod" {
  provider = azurerm.prod
  name     = "rg-demo-network-prod"
  location = var.location
}

resource "azurerm_virtual_network" "prod" {
  provider            = azurerm.prod
  name                = "vnet-demo-prod"
  resource_group_name = azurerm_resource_group.net_prod.name
  location            = var.location
  address_space       = ["10.20.0.0/16"]
}

resource "azurerm_subnet" "prod" {
  provider             = azurerm.prod
  name                 = "snet-workloads"
  resource_group_name  = azurerm_resource_group.net_prod.name
  virtual_network_name = azurerm_virtual_network.prod.name
  address_prefixes     = ["10.20.1.0/24"]
}

# --- Management network (W11 only) ------------------------------------------
resource "azurerm_resource_group" "net_mgmt" {
  provider = azurerm.management
  name     = "rg-demo-network-mgmt"
  location = var.location
}

resource "azurerm_virtual_network" "mgmt" {
  provider            = azurerm.management
  name                = "vnet-demo-mgmt"
  resource_group_name = azurerm_resource_group.net_mgmt.name
  location            = var.location
  address_space       = ["10.30.0.0/16"]
}

resource "azurerm_subnet" "mgmt" {
  provider             = azurerm.management
  name                 = "snet-workloads"
  resource_group_name  = azurerm_resource_group.net_mgmt.name
  virtual_network_name = azurerm_virtual_network.mgmt.name
  address_prefixes     = ["10.30.1.0/24"]
}
