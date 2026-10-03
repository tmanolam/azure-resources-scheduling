terraform {
  required_version = ">= 1.9" # IAC-005

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.0" # IAC-005
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6" # H6: global-uniqueness suffix for globally unique names
    }
    # Note: the azuread provider is intentionally not declared here. It is only
    # needed in phase 2 for the on-demand endpoint's Entra app roles (FR-022/023,
    # L1); add it back then. IAC-005 updated accordingly.
  }

  backend "azurerm" {} # configured via backend.hcl (IAC-002)
}

provider "azurerm" {
  subscription_id = var.subscription_id
  features {}
}
