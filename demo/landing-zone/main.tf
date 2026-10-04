# =============================================================================
# DM-10 — Management group hierarchy (CAF-lite), per DEMO_TENANT_PLAN §2.2
#
#   Tenant Root Group
#   └── demo  (intermediate root; role_assignable_scope)
#       ├── demo-platform ....................... excluded_scope_ids
#       │   ├── demo-platform-management ........ sub-demo-management
#       │   └── demo-platform-connectivity ...... (empty)
#       ├── demo-landingzones ................... in_scope
#       │   ├── demo-workload-np ................ sub-demo-workload-dev
#       │   └── demo-workload-prod .............. sub-demo-workload-prod
#       ├── demo-sandbox ........................ in_scope
#       │   └── demo-sandbox-excluded ........... excluded_scope_ids (S9)
#       └── demo-decommissioned
#
# management_group_id must reference the PARENT's id. Tenant-root parent is
# omitted so `demo` lands directly under the Tenant Root Group.
# =============================================================================

# Intermediate root — the role_assignable_scope for the custom role.
resource "azurerm_management_group" "demo" {
  display_name = var.mg_prefix
  name         = var.mg_prefix
}

# --- Platform (excluded) ---------------------------------------------------
resource "azurerm_management_group" "platform" {
  display_name               = "${var.mg_prefix}-platform"
  name                       = "${var.mg_prefix}-platform"
  parent_management_group_id = azurerm_management_group.demo.id
}

resource "azurerm_management_group" "platform_management" {
  display_name               = "${var.mg_prefix}-platform-management"
  name                       = "${var.mg_prefix}-platform-management"
  parent_management_group_id = azurerm_management_group.platform.id
}

resource "azurerm_management_group" "platform_connectivity" {
  display_name               = "${var.mg_prefix}-platform-connectivity"
  name                       = "${var.mg_prefix}-platform-connectivity"
  parent_management_group_id = azurerm_management_group.platform.id
}

# --- Landing zones (in scope) ----------------------------------------------
resource "azurerm_management_group" "landingzones" {
  display_name               = "${var.mg_prefix}-landingzones"
  name                       = "${var.mg_prefix}-landingzones"
  parent_management_group_id = azurerm_management_group.demo.id
}

resource "azurerm_management_group" "workload_np" {
  display_name               = "${var.mg_prefix}-workload-np"
  name                       = "${var.mg_prefix}-workload-np"
  parent_management_group_id = azurerm_management_group.landingzones.id
}

resource "azurerm_management_group" "workload_prod" {
  display_name               = "${var.mg_prefix}-workload-prod"
  name                       = "${var.mg_prefix}-workload-prod"
  parent_management_group_id = azurerm_management_group.landingzones.id
}

# --- Sandbox (in scope) with a nested excluded child (S9) ------------------
resource "azurerm_management_group" "sandbox" {
  display_name               = "${var.mg_prefix}-sandbox"
  name                       = "${var.mg_prefix}-sandbox"
  parent_management_group_id = azurerm_management_group.demo.id
}

resource "azurerm_management_group" "sandbox_excluded" {
  display_name               = "${var.mg_prefix}-sandbox-excluded"
  name                       = "${var.mg_prefix}-sandbox-excluded"
  parent_management_group_id = azurerm_management_group.sandbox.id
}

# --- Decommissioned --------------------------------------------------------
resource "azurerm_management_group" "decommissioned" {
  display_name               = "${var.mg_prefix}-decommissioned"
  name                       = "${var.mg_prefix}-decommissioned"
  parent_management_group_id = azurerm_management_group.demo.id
}

# =============================================================================
# DM-11 — Place subscriptions in management groups (§2.1, Plan A)
#
# management_group_subscription_association expects the subscription in the
# form "/subscriptions/<id>". Sandbox is optional (may not exist yet).
# =============================================================================
resource "azurerm_management_group_subscription_association" "management" {
  management_group_id = azurerm_management_group.platform_management.id
  subscription_id     = "/subscriptions/${var.management_subscription_id}"
}

resource "azurerm_management_group_subscription_association" "workload_dev" {
  management_group_id = azurerm_management_group.workload_np.id
  subscription_id     = "/subscriptions/${var.workload_dev_subscription_id}"
}

resource "azurerm_management_group_subscription_association" "workload_prod" {
  management_group_id = azurerm_management_group.workload_prod.id
  subscription_id     = "/subscriptions/${var.workload_prod_subscription_id}"
}

resource "azurerm_management_group_subscription_association" "sandbox" {
  count               = var.sandbox_subscription_id == "" ? 0 : 1
  management_group_id = azurerm_management_group.sandbox.id
  subscription_id     = "/subscriptions/${var.sandbox_subscription_id}"
}

# =============================================================================
# DM-12 — Subscription tags (§2.1), via azapi (no azurerm subscription-tag
# resource). Microsoft.Resources/tags is a singleton "default" child of the
# subscription scope.
#
#   sub-demo-management     environment=platform
#   sub-demo-workload-dev   environment=dev
#   sub-demo-workload-prod  Environment=Prod    (mixed case on purpose — N5)
#   sub-demo-sandbox        environment=sandbox, schedule-profile=sandbox-default
# =============================================================================
resource "azapi_update_resource" "tags_management" {
  type        = "Microsoft.Resources/tags@2022-09-01"
  resource_id = "/subscriptions/${var.management_subscription_id}/providers/Microsoft.Resources/tags/default"
  body = {
    properties = {
      tags = {
        environment = "platform"
      }
    }
  }
}

resource "azapi_update_resource" "tags_workload_dev" {
  type        = "Microsoft.Resources/tags@2022-09-01"
  resource_id = "/subscriptions/${var.workload_dev_subscription_id}/providers/Microsoft.Resources/tags/default"
  body = {
    properties = {
      tags = {
        environment = "dev"
      }
    }
  }
}

# Deliberately mixed-case key AND value (Environment=Prod) to prove BR-003 is
# matched case-insensitively (finding N5 / scenario S7).
resource "azapi_update_resource" "tags_workload_prod" {
  type        = "Microsoft.Resources/tags@2022-09-01"
  resource_id = "/subscriptions/${var.workload_prod_subscription_id}/providers/Microsoft.Resources/tags/default"
  body = {
    properties = {
      tags = {
        Environment = "Prod"
      }
    }
  }
}

# Sandbox carries both an environment tag and a subscription-level
# schedule-profile, exercising subscription-level tag inheritance (S3).
resource "azapi_update_resource" "tags_sandbox" {
  count       = var.sandbox_subscription_id == "" ? 0 : 1
  type        = "Microsoft.Resources/tags@2022-09-01"
  resource_id = "/subscriptions/${var.sandbox_subscription_id}/providers/Microsoft.Resources/tags/default"
  body = {
    properties = {
      tags = {
        environment        = "sandbox"
        "schedule-profile" = "sandbox-default"
      }
    }
  }
}
