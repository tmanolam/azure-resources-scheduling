# =============================================================================
# W6 — VM scale set (VMSS handler; fallback state read, N7). Dev subscription.
# =============================================================================
resource "azurerm_resource_group" "w6" {
  provider = azurerm.dev
  name     = "rg-demo-vmss"
  location = var.location
}

resource "azurerm_linux_virtual_machine_scale_set" "w6" {
  provider            = azurerm.dev
  name                = "vmss-demo-w6"
  resource_group_name = azurerm_resource_group.w6.name
  location            = var.location
  sku                 = var.vm_size
  instances           = 1
  admin_username      = var.admin_username
  tags                = { "schedule-profile" = var.standard_profile }

  admin_ssh_key {
    username   = var.admin_username
    public_key = tls_private_key.vm.public_key_openssh
  }

  os_disk {
    caching              = "ReadWrite"
    storage_account_type = "Standard_LRS"
  }

  source_image_reference {
    publisher = local.vm_image.publisher
    offer     = local.vm_image.offer
    sku       = local.vm_image.sku
    version   = local.vm_image.version
  }

  network_interface {
    name    = "nic-demo-w6"
    primary = true
    ip_configuration {
      name      = "ipconfig1"
      primary   = true
      subnet_id = azurerm_subnet.dev.id
    }
  }
}

# =============================================================================
# W7 — PostgreSQL Flexible Server. Order 1 (starts first). Dev subscription.
# =============================================================================
resource "azurerm_resource_group" "w7w8" {
  provider = azurerm.dev
  name     = "rg-demo-db"
  location = var.location
}

resource "azurerm_postgresql_flexible_server" "w7" {
  provider            = azurerm.dev
  name                = "psql-demo-w7"
  resource_group_name = azurerm_resource_group.w7w8.name
  location            = var.location

  version                       = "16"
  administrator_login           = "demopg"
  administrator_password        = random_password.postgres.result
  sku_name                      = "B_Standard_B1ms"
  storage_mb                    = 32768
  zone                          = "1"
  public_network_access_enabled = false

  authentication {
    password_auth_enabled = true
  }

  tags = {
    "schedule-profile" = var.standard_profile
    "schedule-order"   = "1"
  }

  lifecycle {
    # The platform auto-starts a stopped flexible server after 7 days; power
    # state is managed by the scheduler, not Terraform, so ignore it.
    ignore_changes = [zone, high_availability[0].standby_availability_zone]
  }
}

# =============================================================================
# W8 — MySQL Flexible Server. Order 1. Dev subscription. Same RG as W7.
# =============================================================================
resource "azurerm_mysql_flexible_server" "w8" {
  provider            = azurerm.dev
  name                = "mysql-demo-w8"
  resource_group_name = azurerm_resource_group.w7w8.name
  location            = var.location

  administrator_login    = "demomysql"
  administrator_password = random_password.mysql.result
  sku_name               = "B_Standard_B1ms"
  version                = "8.0.21"
  zone                   = "1"

  # DR-07: unlike PostgreSQL flexible server, azurerm's
  # azurerm_mysql_flexible_server treats public_network_access_enabled as a
  # COMPUTED attribute — it cannot be set to false directly on the public-access
  # connectivity method (hashicorp/terraform-provider-azurerm#26156). Fully
  # disabling public access requires private link (a delegated subnet + private
  # DNS zone), which is disproportionate for a cost-controlled demo DB. With no
  # firewall rules created here, the server denies all inbound by default, so it
  # is not reachable; the public endpoint simply exists. Documented as an
  # accepted deviation from DM-23 for MySQL only.

  tags = {
    "schedule-profile" = var.standard_profile
    "schedule-order"   = "1"
  }

  lifecycle {
    ignore_changes = [zone, high_availability[0].standby_availability_zone]
  }
}
