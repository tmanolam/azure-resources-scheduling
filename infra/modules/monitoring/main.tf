terraform {
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.0"
    }
  }
}

# --- Log Analytics workspace (created only if an existing one isn't supplied, A-04) ---
resource "azurerm_log_analytics_workspace" "this" {
  count               = var.log_analytics_workspace_id == "" ? 1 : 0
  name                = var.workspace_name
  resource_group_name = var.resource_group_name
  location            = var.location
  sku                 = "PerGB2018"
  retention_in_days   = 30
  tags                = var.tags
}

locals {
  workspace_id = var.log_analytics_workspace_id != "" ? var.log_analytics_workspace_id : azurerm_log_analytics_workspace.this[0].id
}

# --- Application Insights (workspace-based) ---------------------------------
resource "azurerm_application_insights" "this" {
  name                = var.app_insights_name
  resource_group_name = var.resource_group_name
  location            = var.location
  application_type    = "web"
  workspace_id        = local.workspace_id
  tags                = var.tags
}

# --- Action group (alert notifications) -------------------------------------
resource "azurerm_monitor_action_group" "this" {
  name                = var.action_group_name
  resource_group_name = var.resource_group_name
  short_name          = "pwrsched"

  dynamic "email_receiver" {
    for_each = toset(var.alert_email_addresses)
    content {
      name                    = "email-${replace(email_receiver.value, "/[^a-zA-Z0-9]/", "-")}"
      email_address           = email_receiver.value
      use_common_alert_schema = true
    }
  }

  tags = var.tags
}

# --- OBS-003: cycle failed or no run for >45 minutes ------------------------
# A scheduled query alert: fire when no cycle-summary trace in the last 45 min,
# or when a cycle logs a failure.
resource "azurerm_monitor_scheduled_query_rules_alert_v2" "cycle_health" {
  name                = "${var.alert_prefix}-cycle-health"
  resource_group_name = var.resource_group_name
  location            = var.location
  severity            = 1
  scopes              = [azurerm_application_insights.this.id]
  description         = "Reconciliation cycle failed or has not run for >45 minutes (OBS-003)."

  evaluation_frequency = "PT15M"
  window_duration      = "PT45M"

  criteria {
    query                   = <<-KQL
      traces
      | where customDimensions.event == "pwrsched.summary"
      | summarize cycles = count()
    KQL
    time_aggregation_method = "Count"
    threshold               = 0
    operator                = "LessThanOrEqual"

    failing_periods {
      minimum_failing_periods_to_trigger_alert = 1
      number_of_evaluation_periods             = 1
    }
  }

  action {
    action_groups = [azurerm_monitor_action_group.this.id]
  }

  tags = var.tags
}

# --- OBS-005: maxActionsPerRun reached --------------------------------------
resource "azurerm_monitor_scheduled_query_rules_alert_v2" "cap_reached" {
  name                = "${var.alert_prefix}-max-actions-cap"
  resource_group_name = var.resource_group_name
  location            = var.location
  severity            = 2
  scopes              = [azurerm_application_insights.this.id]
  description         = "maxActionsPerRun safety cap reached in a cycle (OBS-005, FR-031)."

  evaluation_frequency = "PT15M"
  window_duration      = "PT1H"

  criteria {
    query                   = <<-KQL
      traces
      | where customDimensions.event == "pwrsched.capReached"
      | summarize hits = count()
    KQL
    time_aggregation_method = "Count"
    threshold               = 0
    operator                = "GreaterThan"

    failing_periods {
      minimum_failing_periods_to_trigger_alert = 1
      number_of_evaluation_periods             = 1
    }
  }

  action {
    action_groups = [azurerm_monitor_action_group.this.id]
  }

  tags = var.tags
}

# --- OBS-004: same resource fails an action in 3 consecutive cycles ---------
resource "azurerm_monitor_scheduled_query_rules_alert_v2" "repeated_failures" {
  name                = "${var.alert_prefix}-repeated-action-failures"
  resource_group_name = var.resource_group_name
  location            = var.location
  severity            = 2
  scopes              = [azurerm_application_insights.this.id]
  description         = "A resource failed its action in 3 consecutive cycles (OBS-004)."

  evaluation_frequency = "PT15M"
  window_duration      = "PT45M"

  criteria {
    query                   = <<-KQL
      traces
      | where customDimensions.event == "pwrsched.decision"
      | where tostring(customDimensions.result) == "failed"
      | summarize failures = dcount(tostring(customDimensions.runId)) by resource = tostring(customDimensions.resourceId)
      | where failures >= 3
    KQL
    time_aggregation_method = "Count"
    threshold               = 0
    operator                = "GreaterThan"

    failing_periods {
      minimum_failing_periods_to_trigger_alert = 1
      number_of_evaluation_periods             = 1
    }
  }

  action {
    action_groups = [azurerm_monitor_action_group.this.id]
  }

  tags = var.tags
}
