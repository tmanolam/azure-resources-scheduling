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

# --- OBS-003: cycle has not run (no summary) for >45 minutes ----------------
# A scheduled query alert: fire when fewer than one cycle-summary trace appears
# in the window. ``summarize cycles = count()`` yields a single row whose value
# is the count, so the alert must aggregate on that *value* (metric_measure_column
# = "cycles", Total), not on row count — otherwise it always sees one row and can
# never fire (finding H2).
resource "azurerm_monitor_scheduled_query_rules_alert_v2" "cycle_health" {
  name                = "${var.alert_prefix}-cycle-health"
  resource_group_name = var.resource_group_name
  location            = var.location
  severity            = 1
  scopes              = [azurerm_application_insights.this.id]
  description         = "Reconciliation cycle has not run (no summary) for >45 minutes (OBS-003)."

  evaluation_frequency = "PT15M"
  window_duration      = "PT45M"

  criteria {
    query                   = <<-KQL
      traces
      | where customDimensions["pwrsched.event"] == "pwrsched.summary"
      | summarize cycles = count()
    KQL
    time_aggregation_method = "Total"
    metric_measure_column   = "cycles"
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

# --- OBS-003 (second condition): a reconcile cycle threw an exception --------
# The cycle-health alert above covers "did not run"; this covers "ran and
# failed" by watching the exceptions table for the reconcile operation (H2).
resource "azurerm_monitor_scheduled_query_rules_alert_v2" "cycle_exceptions" {
  name                = "${var.alert_prefix}-cycle-exceptions"
  resource_group_name = var.resource_group_name
  location            = var.location
  severity            = 1
  scopes              = [azurerm_application_insights.this.id]
  description         = "A reconciliation cycle threw an exception (OBS-003)."

  evaluation_frequency = "PT15M"
  window_duration      = "PT15M"

  criteria {
    query                   = <<-KQL
      exceptions
      | where operation_Name == "reconcile"
      | summarize failures = count()
    KQL
    time_aggregation_method = "Total"
    metric_measure_column   = "failures"
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
      | where customDimensions["pwrsched.event"] == "pwrsched.capReached"
      | summarize hits = count()
    KQL
    time_aggregation_method = "Total"
    metric_measure_column   = "hits"
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
      | where customDimensions["pwrsched.event"] == "pwrsched.decision"
      | where tostring(customDimensions["pwrsched.result"]) == "failed"
      | summarize failures = dcount(tostring(customDimensions["pwrsched.runId"])) by resource = tostring(customDimensions["pwrsched.resourceId"])
      | where failures >= 3
      | summarize offenders = count()
    KQL
    time_aggregation_method = "Total"
    metric_measure_column   = "offenders"
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
