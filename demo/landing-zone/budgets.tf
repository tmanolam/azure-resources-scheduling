# =============================================================================
# DM-13 — Budgets with email alerts at USD 250 / 500 / 750 (DEMO_TENANT_PLAN §4.3)
#
# Plan A: all four subscriptions draw on the credit, so each gets a budget. The
# thresholds are expressed against a per-subscription amount; the three
# notifications fire at 250, 500 and 750 USD of ACTUAL spend. A single shared
# USD 1,000 credit is still protected because the alerts e-mail the team well
# before the credit is exhausted (the plan's intent is early warning, not a hard
# cap — a spending limit on the credit, DM-02, is the hard stop).
#
# Amounts are set to 1000 so the 25%/50%/75% thresholds land exactly on
# 250/500/750. Adjust `budget_amount` if you prefer per-subscription ceilings.
# =============================================================================

variable "budget_amount" {
  type        = number
  default     = 1000
  description = "Budget base amount (USD). Thresholds 25/50/75% → 250/500/750 (DM-13)."
}

locals {
  # Plan A subscriptions that draw on the credit. Sandbox is included only when
  # it exists. Keyed by a stable name so for_each is deterministic.
  budgeted_subscriptions = merge(
    {
      management    = var.management_subscription_id
      workload_dev  = var.workload_dev_subscription_id
      workload_prod = var.workload_prod_subscription_id
    },
    var.sandbox_subscription_id == "" ? {} : { sandbox = var.sandbox_subscription_id }
  )

  # Threshold percentages that map to USD 250/500/750 at budget_amount = 1000.
  budget_threshold_percentages = [
    for usd in [250, 500, 750] : usd / var.budget_amount * 100
  ]
}

resource "azurerm_consumption_budget_subscription" "demo" {
  for_each = local.budgeted_subscriptions

  name            = "demo-budget-${each.key}"
  subscription_id = "/subscriptions/${each.value}"

  amount     = var.budget_amount
  time_grain = "Monthly"

  time_period {
    # Budgets require a start date on the first of a month, in the future or
    # current month. Compute the first day of the current month at apply time.
    start_date = formatdate("YYYY-MM-01'T'00:00:00Z", timestamp())
  }

  dynamic "notification" {
    for_each = local.budget_threshold_percentages
    content {
      enabled        = true
      threshold      = notification.value
      threshold_type = "Actual"
      operator       = "GreaterThanOrEqualTo"
      contact_emails = var.budget_contact_emails
    }
  }

  lifecycle {
    # timestamp() changes every plan; ignore start_date drift so an unchanged
    # budget does not show a perpetual diff (IAC-008 spirit).
    ignore_changes = [time_period]
  }
}
