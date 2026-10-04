# =============================================================================
# DM-20 — Core workloads W1–W11 (DEMO_TENANT_PLAN §4.1).
#
# "Standard" tag = schedule-profile = var.standard_profile (weekday-0830-1730).
# VMs: Standard_B1s, no public IP, no inbound (NSG on the subnet), SSH key only.
#
# Terraform's `provider` meta-argument cannot be set from a for_each value, so
# the per-subscription VMs are written explicitly. A local helper builds each
# VM's NIC + Linux VM to keep them consistent.
#
# This file: dev-subscription VMs W1–W5. W6 (VMSS), W7/W8 (DBs), W9 (prod),
# W10 (sandbox) and W11 (management) are in their own files.
# =============================================================================

locals {
  # os_disk + source_image shared by every demo VM.
  vm_image = {
    publisher = "Canonical"
    offer     = "ubuntu-24_04-lts"
    sku       = "server"
    version   = "latest"
  }
}

# --- W1 — basic daily schedule (S1) -----------------------------------------
resource "azurerm_resource_group" "w1" {
  provider = azurerm.dev
  name     = "rg-demo-vm"
  location = var.location
}

resource "azurerm_network_interface" "w1" {
  provider            = azurerm.dev
  name                = "nic-demo-w1"
  resource_group_name = azurerm_resource_group.w1.name
  location            = var.location
  ip_configuration {
    name                          = "ipconfig1"
    subnet_id                     = azurerm_subnet.dev.id
    private_ip_address_allocation = "Dynamic"
  }
}

resource "azurerm_linux_virtual_machine" "w1" {
  provider              = azurerm.dev
  name                  = "vm-demo-w1"
  resource_group_name   = azurerm_resource_group.w1.name
  location              = var.location
  size                  = var.vm_size
  admin_username        = var.admin_username
  network_interface_ids = [azurerm_network_interface.w1.id]

  # Own tag opts the VM in (W1 is tagged directly).
  tags = { "schedule-profile" = var.standard_profile }

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

# --- W2 — RG inheritance, MIXED-CASE RG name (S2 / N4) -----------------------
# The RG name must keep its exact casing. The VM has NO own schedule tags; it
# inherits the profile from the resource group's tag.
resource "azurerm_resource_group" "w2" {
  provider = azurerm.dev
  name     = "RG-Demo-MixedCase"
  location = var.location
  tags     = { "schedule-profile" = var.standard_profile }
}

resource "azurerm_network_interface" "w2" {
  provider            = azurerm.dev
  name                = "nic-demo-w2"
  resource_group_name = azurerm_resource_group.w2.name
  location            = var.location
  ip_configuration {
    name                          = "ipconfig1"
    subnet_id                     = azurerm_subnet.dev.id
    private_ip_address_allocation = "Dynamic"
  }
}

resource "azurerm_linux_virtual_machine" "w2" {
  provider              = azurerm.dev
  name                  = "vm-demo-w2"
  resource_group_name   = azurerm_resource_group.w2.name
  location              = var.location
  size                  = var.vm_size
  admin_username        = var.admin_username
  network_interface_ids = [azurerm_network_interface.w2.id]

  # No schedule tags of its own — inheritance from the RG is the point of W2.
  tags = {}

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

# --- W3 — overrides (S4/S5) --------------------------------------------------
resource "azurerm_resource_group" "w3" {
  provider = azurerm.dev
  name     = "rg-demo-override"
  location = var.location
}

resource "azurerm_network_interface" "w3" {
  provider            = azurerm.dev
  name                = "nic-demo-w3"
  resource_group_name = azurerm_resource_group.w3.name
  location            = var.location
  ip_configuration {
    name                          = "ipconfig1"
    subnet_id                     = azurerm_subnet.dev.id
    private_ip_address_allocation = "Dynamic"
  }
}

resource "azurerm_linux_virtual_machine" "w3" {
  provider              = azurerm.dev
  name                  = "vm-demo-w3"
  resource_group_name   = azurerm_resource_group.w3.name
  location              = var.location
  size                  = var.vm_size
  admin_username        = var.admin_username
  network_interface_ids = [azurerm_network_interface.w3.id]
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

# --- W4 — opt-out (S6): Standard + schedule-enabled=false --------------------
resource "azurerm_resource_group" "w4" {
  provider = azurerm.dev
  name     = "rg-demo-optout"
  location = var.location
}

resource "azurerm_network_interface" "w4" {
  provider            = azurerm.dev
  name                = "nic-demo-w4"
  resource_group_name = azurerm_resource_group.w4.name
  location            = var.location
  ip_configuration {
    name                          = "ipconfig1"
    subnet_id                     = azurerm_subnet.dev.id
    private_ip_address_allocation = "Dynamic"
  }
}

resource "azurerm_linux_virtual_machine" "w4" {
  provider              = azurerm.dev
  name                  = "vm-demo-w4"
  resource_group_name   = azurerm_resource_group.w4.name
  location              = var.location
  size                  = var.vm_size
  admin_username        = var.admin_username
  network_interface_ids = [azurerm_network_interface.w4.id]

  tags = {
    "schedule-profile" = var.standard_profile
    "schedule-enabled" = "false"
  }

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

# --- W5 — powered-off (not deallocated) test (S11 / H4) ----------------------
resource "azurerm_resource_group" "w5" {
  provider = azurerm.dev
  name     = "rg-demo-poweroff"
  location = var.location
}

resource "azurerm_network_interface" "w5" {
  provider            = azurerm.dev
  name                = "nic-demo-w5"
  resource_group_name = azurerm_resource_group.w5.name
  location            = var.location
  ip_configuration {
    name                          = "ipconfig1"
    subnet_id                     = azurerm_subnet.dev.id
    private_ip_address_allocation = "Dynamic"
  }
}

resource "azurerm_linux_virtual_machine" "w5" {
  provider              = azurerm.dev
  name                  = "vm-demo-w5"
  resource_group_name   = azurerm_resource_group.w5.name
  location              = var.location
  size                  = var.vm_size
  admin_username        = var.admin_username
  network_interface_ids = [azurerm_network_interface.w5.id]
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
