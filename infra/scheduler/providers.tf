terraform {
  required_version = ">= 1.9" # IAC-005

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.0" # IAC-005
    }
    azuread = {
      source  = "hashicorp/azuread"
      version = "~> 3.0" # IAC-005
    }
  }

  backend "azurerm" {} # configured via backend.hcl (IAC-002)
}

provider "azurerm" {
  subscription_id = var.subscription_id
  features {}
}

provider "azuread" {}
