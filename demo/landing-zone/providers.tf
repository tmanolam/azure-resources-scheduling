# demo/landing-zone — CAF-lite management group hierarchy, subscription
# placement + tags, and budgets for the disposable demo tenant.
#
# See docs/archive/demo-verification/DEMO_TENANT_PLAN.md §2.2 (hierarchy), §2.1 (subscriptions/tags) and
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

  # State backend.
  #
  # Default: LOCAL state (a disposable demo tenant does not require remote
  # state). The current demo state lives on the operator laptop that ran the
  # applies.
  #
  # OPTIONAL remote backend (recommended to avoid split-brain state across
  # laptops — see docs/DEMO_STATE_BACKEND.md). To switch:
  #   1. Uncomment the backend block below.
  #   2. Copy backend.hcl.example → backend.hcl and fill in the demo state
  #      storage account (reuse infra/tenants/demo.backend.hcl's account; use a
  #      distinct key, e.g. demo/landing-zone.tfstate).
  #   3. One-time, FROM THE LAPTOP THAT HOLDS THE LOCAL STATE, run:
  #        terraform init -migrate-state -backend-config=backend.hcl
  #      Terraform copies the existing local state up to the backend. Running
  #      this from a laptop WITHOUT the local state would start empty and plan
  #      to recreate everything — do not do that.
  #   4. Afterwards, on any machine: terraform init -reconfigure -backend-config=backend.hcl
  #
  backend "azurerm" {} # configured via backend.hcl
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
