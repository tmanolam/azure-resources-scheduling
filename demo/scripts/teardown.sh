#!/usr/bin/env bash
#
# DM-43 — teardown.sh — tear down the demo per DEMO_TENANT_PLAN §9, in order,
# asking for confirmation before destroying. Leaves no billable resources.
#
# Order (§9):
#   1. Set dry_run = true on the scheduler (stops all actions within a cycle).
#   2. terraform destroy demo/workloads (optional components first: SQL MI, AppGw, AKS).
#   3. (Export evidence first if wanted: collect-evidence.sh final)
#   4. Destroy the scheduler via ./infra/deploy.sh demo destroy (DR-01: this
#      re-initialises the demo backend first, so the destroy targets the demo
#      state — never whatever infra/scheduler was last pointed at).
#   5. terraform destroy demo/landing-zone (subscriptions return to Tenant Root).
#   6. Remove subscription tags left by azapi_update_resource (DR-11) — manual.
#   7. Delete the demo-only Terraform state storage account (if any) — manual.
#   8. Turn off elevated access (DM-04) — manual.
#   9. Cancel subscriptions when the tenant is no longer needed — manual.
#
# This script performs steps 2, 4 and 5 and reminds you about the manual steps.
# Step 1 is done via infra/tenants/demo.tfvars + ./infra/deploy.sh demo apply.
#
# Usage:
#   teardown.sh [--yes]
#
# --yes skips the interactive confirmation (use with care).

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/common.sh"
require_az
command -v terraform >/dev/null || die "terraform is required."

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
DEMO_BACKEND="$REPO_ROOT/infra/tenants/demo.backend.hcl"
ASSUME_YES=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --yes)     ASSUME_YES=true; shift ;;
    -h|--help) sed -n '2,24p' "$0"; exit 0 ;;
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
log "Repo root: $REPO_ROOT"
echo

_bold "Reminder — step 1: set dry_run = true in infra/tenants/demo.tfvars and run"
log  "  ./infra/deploy.sh demo apply   BEFORE teardown, so the scheduler stops acting."
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

# --- Step 4: destroy the scheduler via the per-tenant wrapper (DR-01) -------
_bold "Step 4 — destroy the scheduler (./infra/deploy.sh demo destroy)"
if [[ -f "$DEMO_BACKEND" ]]; then
  log "Backend to be used (demo state):"
  grep -E '^(storage_account_name|container_name|key)' "$DEMO_BACKEND" | sed 's/^/    /'
else
  die "missing $DEMO_BACKEND — copy infra/tenants/demo.backend.hcl.example and fill it."
fi
confirm "Destroy the scheduler (Function App, App Config, custom role + assignments) in the DEMO state above?"
# deploy.sh demo destroy runs 'init -reconfigure -backend-config=demo.backend.hcl'
# first, so the destroy is bound to the demo state, not a stale backend.
"$REPO_ROOT/infra/deploy.sh" demo destroy
changed "scheduler destroyed (demo state)"
echo

# --- Step 5: destroy the landing zone ---------------------------------------
_bold "Step 5 — destroy demo/landing-zone (subscriptions return to Tenant Root)"
confirm "Destroy the management groups, placements, tags and budgets?"
terraform -chdir="$REPO_ROOT/demo/landing-zone" destroy -auto-approve
changed "demo/landing-zone destroyed"
echo

_bold "Terraform destroys complete. Remaining MANUAL steps (§9):"
log "6. (DR-11) Remove subscription tags left by azapi (terraform destroy does NOT clear them):"
log "     az tag update --operation Delete --resource-id /subscriptions/<id> \\"
log "       --tags environment schedule-profile   # on each demo subscription"
log "7. Delete the demo-only Terraform state storage account, if you created one."
log "8. Turn OFF elevated access (DM-04): Entra ID → Properties → Access management = No."
log "9. Cancel the subscriptions when the tenant is no longer needed."
