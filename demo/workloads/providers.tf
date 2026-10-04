# demo/workloads — the demo workloads W1–W14 that exercise every scheduler
# behaviour (DEMO_TENANT_PLAN §4). Core W1–W11 always deploy; W12–W14 are
# toggled. All in southeastasia. No product changes — this lives under demo/.
#
# All four subscriptions draw on the credit (plan v0.3 — the single-subscription
# fallback was removed). Workloads span three subscriptions: dev (non-prod),
# prod (W9 only), management (W11 only). Provider aliases target each.

terraform {
  required_version = ">= 1.9"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
    tls = {
      source  = "hashicorp/tls"
      version = "~> 4.0"
    }
  }
}

# Non-production workloads (W1–W8, W12–W14).
provider "azurerm" {
  alias           = "dev"
  subscription_id = var.workload_dev_subscription_id
  features {}
}

# Production — only W9 (proves BR-003 hard exclusion).
provider "azurerm" {
  alias           = "prod"
  subscription_id = var.workload_prod_subscription_id
  features {}
}

# Management — only W11 (proves platform-MG exclusion).
provider "azurerm" {
  alias           = "management"
  subscription_id = var.management_subscription_id
  features {}
}

# Sandbox — only W10 (subscription-level tag inheritance). Points at the sandbox
# subscription when set; otherwise falls back to dev so the provider is always
# valid (W10 itself is count-gated on sandbox_subscription_id being set).
provider "azurerm" {
  alias           = "sandbox"
  subscription_id = var.sandbox_subscription_id == "" ? var.workload_dev_subscription_id : var.sandbox_subscription_id
  features {}
}
