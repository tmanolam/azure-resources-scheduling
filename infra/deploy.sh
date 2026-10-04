#!/usr/bin/env bash
#
# deploy.sh — deploy the Resource Power Scheduler to a specific tenant.
#
# One codebase, many configurations: the Terraform root (infra/scheduler) is
# shared; this wrapper selects a tenant's var-file and state backend from
# infra/tenants/ and runs the requested Terraform action.
#
# Usage:
#   ./infra/deploy.sh <tenant> <command>
#
#   <tenant>   Name matching infra/tenants/<tenant>.tfvars and
#              infra/tenants/<tenant>.backend.hcl
#   <command>  one of: init | plan | apply | output | destroy
#
# Examples:
#   ./infra/deploy.sh contoso plan
#   ./infra/deploy.sh contoso apply
#
# Before running, sign in to the TARGET tenant:
#   az login --tenant <tenant-aad-id>
#   export ARM_SUBSCRIPTION_ID=<management-subscription-id>
#   export ARM_TENANT_ID=<tenant-aad-id>

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="${SCRIPT_DIR}/scheduler"
TENANTS_DIR="${SCRIPT_DIR}/tenants"

die() {
  echo "error: $*" >&2
  exit 1
}

usage() {
  grep '^#' "$0" | sed 's/^# \{0,1\}//' | sed '1d'
  exit "${1:-0}"
}

[[ $# -eq 2 ]] || { usage 1; }

TENANT="$1"
COMMAND="$2"

# Validate tenant name: lowercase alphanumerics and dashes only (defends against
# path traversal / injection via the argument).
[[ "${TENANT}" =~ ^[a-z0-9-]+$ ]] || die "invalid tenant name: ${TENANT} (use lowercase letters, digits, dashes)"

VAR_FILE="${TENANTS_DIR}/${TENANT}.tfvars"
BACKEND_FILE="${TENANTS_DIR}/${TENANT}.backend.hcl"

[[ -f "${VAR_FILE}" ]]     || die "missing var-file: ${VAR_FILE} (copy example.tfvars.example)"
[[ -f "${BACKEND_FILE}" ]] || die "missing backend:  ${BACKEND_FILE} (copy example.backend.hcl.example)"

echo "==> Tenant:  ${TENANT}"
echo "==> Root:    ${ROOT_DIR}"
echo "==> Command: ${COMMAND}"
echo "==> Reminder: ensure 'az login --tenant <${TENANT}-aad-id>' and ARM_SUBSCRIPTION_ID are set for THIS tenant."
echo

# Re-init against this tenant's backend. -reconfigure switches cleanly when
# moving between tenants in the same working directory.
init() {
  terraform -chdir="${ROOT_DIR}" init -reconfigure -input=false \
    -backend-config="${BACKEND_FILE}"
}

case "${COMMAND}" in
  init)
    init
    ;;
  plan)
    init
    terraform -chdir="${ROOT_DIR}" plan -input=false \
      -var-file="${VAR_FILE}" -out="${TENANT}.tfplan"
    ;;
  apply)
    init
    # Require a fresh saved plan (M7). Applying a var-file directly with
    # -input=false cannot prompt and fails; and reusing a stale .tfplan is
    # rejected by Terraform. So: insist on a plan, apply it, then delete it.
    PLAN_FILE="${ROOT_DIR}/${TENANT}.tfplan"
    [[ -f "${PLAN_FILE}" ]] || die "no saved plan for '${TENANT}'. Run './infra/deploy.sh ${TENANT} plan' first, review it, then apply."
    terraform -chdir="${ROOT_DIR}" apply -input=false "${TENANT}.tfplan"
    # Delete the plan so a later apply cannot reuse this now-stale one (M7).
    rm -f "${PLAN_FILE}"
    echo "==> Applied and removed ${TENANT}.tfplan (run 'plan' again before the next apply)."
    ;;
  output)
    init
    terraform -chdir="${ROOT_DIR}" output
    ;;
  destroy)
    init
    echo "WARNING: this will destroy the scheduler in tenant '${TENANT}'."
    # No -input=false here: destroy needs Terraform's interactive "yes" prompt.
    # With -input=false and no -auto-approve, Terraform cannot prompt and aborts
    # (same class of bug M7 fixed for apply). DR-12.
    terraform -chdir="${ROOT_DIR}" destroy -var-file="${VAR_FILE}"
    ;;
  *)
    die "unknown command: ${COMMAND} (use init|plan|apply|output|destroy)"
    ;;
esac
