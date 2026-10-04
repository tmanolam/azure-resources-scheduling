# demo/workloads — the demo workloads W1–W14 that exercise every scheduler
# behaviour (DEMO_TENANT_PLAN §4). Core W1–W11 always deploy; W12–W14 are
# toggled. All in southeastasia. No product changes — this lives under demo/.
#
# Plan A (default): workloads span three subscriptions (dev, prod, management).
# Plan B (var.plan_b = true): all non-prod workloads collapse into the dev
# subscription using resource groups; only the prod VM (W9) stays in prod.
#
# Provider aliases let one root target multiple subscriptions. Each workload
# resource sets `provider =` to the right alias; a local indirection makes the
# non-prod alias follow the Plan A/B switch.

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

# Non-production workloads (W1–W8, W10, W12–W14).
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

# Management — only W11 (proves platform-MG exclusion). Under Plan B this is the
# same subscription as dev, but kept as a distinct alias so the config is uniform.
provider "azurerm" {
  alias           = "management"
  subscription_id = var.plan_b ? var.workload_dev_subscription_id : var.management_subscription_id
  features {}
}

# Sandbox — only W10 (subscription-level tag inheritance). Falls back to dev when
# the sandbox subscription is not set or under Plan B. When sandbox_subscription_id
# is empty this alias simply points at dev; W10 is count-gated separately.
provider "azurerm" {
  alias           = "sandbox"
  subscription_id = (var.plan_b || var.sandbox_subscription_id == "") ? var.workload_dev_subscription_id : var.sandbox_subscription_id
  features {}
}
