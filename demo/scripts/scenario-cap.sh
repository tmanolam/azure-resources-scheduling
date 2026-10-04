#!/usr/bin/env bash
#
# DM-40 — Toggle the maxActionsPerRun cap for scenario S14 (action cap + OBS-005
# alert). Sets or restores the App Configuration key pwrsched:maxActionsPerRun.
#
# NOTE: the authoritative source of this value is terraform.tfvars
# (var.max_actions_per_run), written to App Configuration by Terraform. This
# script changes the App Configuration key DIRECTLY for a quick, reversible test;
# restore it to 200 afterwards (or re-apply Terraform) so config matches IaC.
#
# Usage:
#   scenario-cap.sh set   --appconfig <appcs-name> --value 2
#   scenario-cap.sh restore --appconfig <appcs-name> [--value 200]

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/common.sh"
require_az

ACTION="${1:-}"; shift || true
APPCONFIG=""; VALUE=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --appconfig) APPCONFIG="$2"; shift 2 ;;
    --value)     VALUE="$2"; shift 2 ;;
    -h|--help) sed -n '2,15p' "$0"; exit 0 ;;
    *) die "Unknown argument: $1" ;;
  esac
done
[[ -n "$APPCONFIG" ]] || die "--appconfig <appcs-name> is required."

KEY="pwrsched:maxActionsPerRun"

case "$ACTION" in
  set)     [[ -n "$VALUE" ]] || VALUE=2 ;;
  restore) [[ -n "$VALUE" ]] || VALUE=200 ;;
  *) die "First argument must be 'set' or 'restore'." ;;
esac

_bold "Setting $KEY = $VALUE in App Configuration '$APPCONFIG'"
az appconfig kv set --name "$APPCONFIG" --key "$KEY" --value "$VALUE" --yes --only-show-errors >/dev/null
changed "$KEY = $VALUE (effective next cycle)"
if [[ "$ACTION" == "set" ]]; then
  log "Now trigger many actions (e.g. override the dev subscription running) to hit the cap."
  log "Afterwards: scenario-cap.sh restore --appconfig $APPCONFIG   (and/or re-apply Terraform)."
fi
