#!/usr/bin/env bash
#
# DM-40 — Power off a VM from INSIDE the OS so it is StoppedAllocated (still
# billed), NOT deallocated (scenario S11a/S11b, finding H4). The scheduler
# should then deallocate it (desired Stopped) or start it (desired Running).
#
# Uses `az vm run-command invoke` to run `sudo poweroff` inside the guest, which
# leaves the VM in PowerState/stopped (allocated) rather than deallocated.
#
# Usage:
#   scenario-poweroff-vm.sh --subscription <dev-sub-id> [--rg rg-demo-poweroff] [--name vm-demo-w5]

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/common.sh"
require_az

SUB=""; RG="rg-demo-poweroff"; NAME="vm-demo-w5"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --subscription) SUB="$2"; shift 2 ;;
    --rg)           RG="$2"; shift 2 ;;
    --name)         NAME="$2"; shift 2 ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) die "Unknown argument: $1" ;;
  esac
done
[[ -n "$SUB" ]] || die "--subscription <dev-sub-id> is required."

az account set --subscription "$SUB"

_bold "Powering off $NAME from inside the OS (StoppedAllocated test, S11)"
log "Running 'sudo poweroff' via run-command (the VM must be running first)."

az vm run-command invoke \
  -g "$RG" -n "$NAME" \
  --command-id RunShellScript \
  --scripts "sudo poweroff" \
  --only-show-errors >/dev/null || true

changed "poweroff issued inside $NAME — it should become StoppedAllocated (billed)"
log "Verify with: az vm get-instance-view -g $RG -n $NAME --query 'instanceView.statuses[?starts_with(code, \`PowerState\`)].code' -o tsv"
log "Expected: PowerState/stopped (not deallocated). The next cycle corrects it per the desired state."
