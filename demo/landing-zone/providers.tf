# demo/landing-zone — CAF-lite management group hierarchy, subscription
# placement + tags, and budgets for the disposable demo tenant.
#
# See docs/DEMO_TENANT_PLAN.md §2.2 (hierarchy), §2.1 (subscriptions/tags) and
# §4.3/DM-13 (budgets). This is demo-only infrastructure; it lives under demo/
# and never changes the shipped product (infra/).
#
# Plan A: all four subscriptions draw on the credit (DEMO_TENANT_PLAN §2.1).

terraform {
  required_version = ">= 1.9"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.0"
    }
    # azapi is used for subscription-level tags: azurerm has no first-class
    # subscription tag resource (DM-12). Microsoft.Resources/tags @ default.
    azapi = {
      source  = "Azure/azapi"
      version = "~> 2.0"
    }
  }

  # Demo-only: local state is fine for a disposable tenant. The shipped product
  # (infra/scheduler) uses a remote azurerm backend; the demo does not need one.
  # Switch to a backend block here if you prefer remote state for the demo.
}

provider "azurerm" {
  # The management subscription hosts the scheduler and (optionally) the demo
  # state. Any subscription in the tenant works for MG/tag operations.
  subscription_id = var.management_subscription_id
  features {}
}

provider "azapi" {
  subscription_id = var.management_subscription_id
}
