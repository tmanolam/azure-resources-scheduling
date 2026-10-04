# =============================================================================
# W9 — Production VM (S7 production exclusion; C1, N5). PROD subscription.
# Tagged Standard, but the subscription's Environment=Prod tag hard-excludes it.
# =============================================================================
resource "azurerm_resource_group" "w9" {
  provider = azurerm.prod
  name     = "rg-demo-prod"
  location = var.location
}

resource "azurerm_network_interface" "w9" {
  provider            = azurerm.prod
  name                = "nic-demo-w9"
  resource_group_name = azurerm_resource_group.w9.name
  location            = var.location
  ip_configuration {
    name                          = "ipconfig1"
    subnet_id                     = azurerm_subnet.prod.id
    private_ip_address_allocation = "Dynamic"
  }
}

resource "azurerm_linux_virtual_machine" "w9" {
  provider              = azurerm.prod
  name                  = "vm-demo-w9"
  resource_group_name   = azurerm_resource_group.w9.name
  location              = var.location
  size                  = var.vm_size
  admin_username        = var.admin_username
  network_interface_ids = [azurerm_network_interface.w9.id]
  tags                  = { "schedule-profile" = var.standard_profile }

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
}

# =============================================================================
# W10 — Sandbox VM (S3 subscription-level inheritance). SANDBOX subscription.
#
# The VM has NO own schedule tags and its RG has none either: it inherits
# schedule-profile=sandbox-default from the SUBSCRIPTION tag (set in
# demo/landing-zone, DM-12).
#
# Plan A: created in the sandbox subscription (requires sandbox_subscription_id).
# When the sandbox subscription is not yet created, W10 is skipped; run scenario
# S3 once the subscription exists and is set.
# =============================================================================
locals {
  deploy_w10 = var.sandbox_subscription_id != ""
}

resource "azurerm_resource_group" "w10_net" {
  count    = local.deploy_w10 ? 1 : 0
  provider = azurerm.sandbox
  name     = "rg-demo-sandbox-network"
  location = var.location
}

resource "azurerm_virtual_network" "w10" {
  count               = local.deploy_w10 ? 1 : 0
  provider            = azurerm.sandbox
  name                = "vnet-demo-sandbox"
  resource_group_name = azurerm_resource_group.w10_net[0].name
  location            = var.location
  address_space       = ["10.40.0.0/16"]
}

resource "azurerm_subnet" "w10" {
  count                = local.deploy_w10 ? 1 : 0
  provider             = azurerm.sandbox
  name                 = "snet-workloads"
  resource_group_name  = azurerm_resource_group.w10_net[0].name
  virtual_network_name = azurerm_virtual_network.w10[0].name
  address_prefixes     = ["10.40.1.0/24"]
}

resource "azurerm_resource_group" "w10" {
  count    = local.deploy_w10 ? 1 : 0
  provider = azurerm.sandbox
  name     = "rg-demo-sandbox"
  location = var.location
  # No schedule-profile tag here: inheritance comes from the subscription (S3).
}

resource "azurerm_network_interface" "w10" {
  count               = local.deploy_w10 ? 1 : 0
  provider            = azurerm.sandbox
  name                = "nic-demo-w10"
  resource_group_name = azurerm_resource_group.w10[0].name
  location            = var.location
  ip_configuration {
    name                          = "ipconfig1"
    subnet_id                     = azurerm_subnet.w10[0].id
    private_ip_address_allocation = "Dynamic"
  }
}

resource "azurerm_linux_virtual_machine" "w10" {
  count                 = local.deploy_w10 ? 1 : 0
  provider              = azurerm.sandbox
  name                  = "vm-demo-w10"
  resource_group_name   = azurerm_resource_group.w10[0].name
  location              = var.location
  size                  = var.vm_size
  admin_username        = var.admin_username
  network_interface_ids = [azurerm_network_interface.w10[0].id]
  tags                  = {} # inherits from the subscription tag

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
}

# =============================================================================
# W11 — Management VM (S8 platform exclusion). MANAGEMENT subscription. Tagged
# Standard on the VM, but it sits under the Platform MG (excluded_scope_ids),
# so the scheduler never touches it.
# =============================================================================
resource "azurerm_resource_group" "w11" {
  provider = azurerm.management
  name     = "rg-demo-platform"
  location = var.location
}

resource "azurerm_network_interface" "w11" {
  provider            = azurerm.management
  name                = "nic-demo-w11"
  resource_group_name = azurerm_resource_group.w11.name
  location            = var.location
  ip_configuration {
    name                          = "ipconfig1"
    subnet_id                     = azurerm_subnet.mgmt.id
    private_ip_address_allocation = "Dynamic"
  }
}

resource "azurerm_linux_virtual_machine" "w11" {
  provider              = azurerm.management
  name                  = "vm-demo-w11"
  resource_group_name   = azurerm_resource_group.w11.name
  location              = var.location
  size                  = var.vm_size
  admin_username        = var.admin_username
  network_interface_ids = [azurerm_network_interface.w11.id]
  tags                  = { "schedule-profile" = var.standard_profile }

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
}
