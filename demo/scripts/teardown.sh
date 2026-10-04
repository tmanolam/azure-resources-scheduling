#!/usr/bin/env bash
#
# DM-43 — teardown.sh — tear down the demo per DEMO_TENANT_PLAN §9, in order,
# asking for confirmation before destroying. Leaves no billable resources.
#
# Order (§9):
#   1. Set dry_run = true on the scheduler (stops all actions within a cycle).
#   2. terraform destroy demo/workloads (optional components first: SQL MI, AppGw, AKS).
#   3. (Export evidence first if wanted: collect-evidence.sh final)
#   4. terraform destroy infra/scheduler with demo.tfvars.
#   5. terraform destroy demo/landing-zone (subscriptions return to Tenant Root).
#   6. Delete the demo-only Terraform state storage account (if any) — manual.
#   7. Turn off elevated access (DM-04) — manual.
#   8. Cancel subscriptions when the tenant is no longer needed — manual.
#
# This script performs steps 2, 4 and 5 (the Terraform destroys) and reminds you
# about the manual steps. Step 1 is done via the scheduler tfvars + apply.
#
# Usage:
#   teardown.sh [--demo-tfvars demo/scheduler/demo.tfvars] [--yes]
#
# --yes skips the interactive confirmation (use with care).

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/common.sh"
require_az
command -v terraform >/dev/null || die "terraform is required."

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
DEMO_TFVARS="$REPO_ROOT/demo/scheduler/demo.tfvars"
ASSUME_YES=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --demo-tfvars) DEMO_TFVARS="$2"; shift 2 ;;
    --yes)         ASSUME_YES=true; shift ;;
    -h|--help) sed -n '2,22p' "$0"; exit 0 ;;
    *) die "Unknown argument: $1" ;;
  esac
done

confirm() {
  $ASSUME_YES && return 0
  local prompt="$1"
  read -r -p "  $prompt [type 'destroy' to proceed]: " ans
  [[ "$ans" == "destroy" ]] || die "Aborted (expected 'destroy')."
}

_bold "Demo teardown (DEMO_TENANT_PLAN §9)"
log "This DESTROYS the demo workloads, scheduler and landing zone. It is irreversible."
echo

_bold "Reminder — step 1: set dry_run = true in $DEMO_TFVARS and apply BEFORE teardown,"
log  "so the scheduler stops acting within a cycle. (Not done automatically here.)"
_bold "Reminder — step 3: export evidence first if you want to keep it:"
log  "  demo/scripts/collect-evidence.sh final"
echo

# --- Step 2: destroy workloads (optional components implicitly included) ----
_bold "Step 2 — destroy demo/workloads"
confirm "Destroy ALL demo workloads (W1–W14)?"
# demo/workloads auto-loads its own terraform.tfvars (subscription IDs, toggles).
terraform -chdir="$REPO_ROOT/demo/workloads" destroy -auto-approve
changed "demo/workloads destroyed"
echo

# --- Step 4: destroy the scheduler ------------------------------------------
_bold "Step 4 — destroy infra/scheduler (with demo.tfvars)"
confirm "Destroy the scheduler (Function App, App Config, custom role + assignments)?"
if [[ -f "$DEMO_TFVARS" ]]; then
  terraform -chdir="$REPO_ROOT/infra/scheduler" destroy -var-file="$DEMO_TFVARS" -auto-approve
else
  log "WARN: $DEMO_TFVARS not found; running destroy without -var-file (may prompt)."
  terraform -chdir="$REPO_ROOT/infra/scheduler" destroy -auto-approve
fi
changed "infra/scheduler destroyed"
echo

# --- Step 5: destroy the landing zone ---------------------------------------
_bold "Step 5 — destroy demo/landing-zone (subscriptions return to Tenant Root)"
confirm "Destroy the management groups, placements, tags and budgets?"
terraform -chdir="$REPO_ROOT/demo/landing-zone" destroy -auto-approve
changed "demo/landing-zone destroyed"
echo

_bold "Terraform destroys complete. Remaining MANUAL steps (§9):"
log "6. Delete the demo-only Terraform state storage account, if you created one."
log "7. Turn OFF elevated access (DM-04): Entra ID → Properties → Access management = No."
log "8. Cancel the subscriptions when the tenant is no longer needed (a Plan B PAYG sub keeps billing)."
