#!/usr/bin/env bash
#
# DM-05 — Register the resource providers the demo workloads need, in each
# subscription. See docs/DEMO_TENANT_PLAN.md §3 (prerequisites) and §4 (workloads).
#
# Idempotent: re-running is safe. `az provider register` is a no-op for a
# provider that is already Registered, and registration is per-subscription.
#
# Usage:
#   ./register-providers.sh <subscription-id-or-name> [<subscription-id-or-name> ...]
#   ./register-providers.sh --all          # every subscription the CLI can see
#   ./register-providers.sh --wait=false ...   # fire-and-forget (don't poll for Registered)
#
# Notes:
#   - sub-demo-sandbox does not exist yet (Azure quota). Omit it now and re-run
#     this script with just that subscription once it is created.
#   - Requires Contributor-or-equivalent (*/register/action) on each subscription,
#     which DM-04 elevated access provides.

set -euo pipefail

# Providers required by the demo (DM-05). Keep in sync with DEMO_TENANT_PLAN.md.
PROVIDERS=(
  Microsoft.Compute
  Microsoft.Network
  Microsoft.ContainerService
  Microsoft.DBforPostgreSQL
  Microsoft.DBforMySQL
  Microsoft.Sql
  Microsoft.Web
  Microsoft.App
  Microsoft.AppConfiguration
  Microsoft.Insights
  Microsoft.OperationalInsights
  Microsoft.Storage
)

WAIT=true
SUBS=()

for arg in "$@"; do
  case "$arg" in
    --all)        SUBS=(--all) ;;
    --wait=false) WAIT=false ;;
    --wait=true)  WAIT=true ;;
    -h|--help)    sed -n '2,25p' "$0"; exit 0 ;;
    -*)           echo "Unknown option: $arg" >&2; exit 2 ;;
    *)            SUBS+=("$arg") ;;
  esac
done

if [[ ${#SUBS[@]} -eq 0 ]]; then
  echo "Error: pass one or more subscription ids/names, or --all." >&2
  echo "Example: $0 sub-demo-management sub-demo-workload-dev sub-demo-workload-prod" >&2
  exit 2
fi

# Expand --all into the list of accessible subscription ids.
if [[ "${SUBS[0]}" == "--all" ]]; then
  mapfile -t SUBS < <(az account list --query "[?state=='Enabled'].id" -o tsv)
  echo "Discovered ${#SUBS[@]} enabled subscription(s)."
fi

overall_rc=0

for sub in "${SUBS[@]}"; do
  echo
  echo "=== Subscription: $sub ==="

  if ! az account set --subscription "$sub" 2>/dev/null; then
    echo "  SKIP: cannot access subscription '$sub' (not created yet or no permission)." >&2
    overall_rc=1
    continue
  fi

  display_name=$(az account show --query name -o tsv)
  echo "  Active: $display_name"

  # Kick off registration for every provider (idempotent).
  for rp in "${PROVIDERS[@]}"; do
    echo "  - registering $rp ..."
    az provider register --namespace "$rp" --only-show-errors >/dev/null
  done

  if [[ "$WAIT" != "true" ]]; then
    echo "  Registration requested (not waiting). Check later with:"
    echo "    az provider list --query \"[?namespace=='Microsoft.Compute'].registrationState\" -o tsv"
    continue
  fi

  # Poll until every provider reaches Registered (or time out).
  echo "  Waiting for all providers to reach 'Registered' ..."
  deadline=$(( $(date +%s) + 600 ))   # 10-minute budget per subscription
  while :; do
    pending=()
    for rp in "${PROVIDERS[@]}"; do
      state=$(az provider show --namespace "$rp" --query registrationState -o tsv 2>/dev/null || echo "Unknown")
      if [[ "$state" != "Registered" ]]; then
        pending+=("$rp:$state")
      fi
    done

    if [[ ${#pending[@]} -eq 0 ]]; then
      echo "  OK: all ${#PROVIDERS[@]} providers Registered."
      break
    fi

    if [[ $(date +%s) -ge $deadline ]]; then
      echo "  TIMEOUT: still pending after 10 min: ${pending[*]}" >&2
      overall_rc=1
      break
    fi

    sleep 15
  done
done

echo
if [[ $overall_rc -eq 0 ]]; then
  echo "DM-05 complete for the subscriptions processed."
else
  echo "DM-05 finished with warnings (some subscriptions skipped or timed out). See above." >&2
fi
exit $overall_rc
