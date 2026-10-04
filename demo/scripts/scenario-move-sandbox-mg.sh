#!/usr/bin/env bash
#
# DM-40 — Move the sandbox subscription between management groups to prove
# nested-MG exclusion (scenario S9). Moving it into demo-sandbox-excluded (an
# excluded_scope) should make W10 disappear from decisions; moving it back
# should restore it.
#
# Usage:
#   scenario-move-sandbox-mg.sh exclude --subscription <sandbox-sub-id> [--prefix demo]
#   scenario-move-sandbox-mg.sh restore --subscription <sandbox-sub-id> [--prefix demo]
#
# NOTE: MG moves can take several minutes to propagate to Resource Graph; wait
# 2–3 cycles before/after checking.

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/common.sh"
require_az

ACTION="${1:-}"; shift || true
SUB=""; PREFIX="demo"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --subscription) SUB="$2"; shift 2 ;;
    --prefix)       PREFIX="$2"; shift 2 ;;
    -h|--help) sed -n '2,14p' "$0"; exit 0 ;;
    *) die "Unknown argument: $1" ;;
  esac
done
[[ -n "$SUB" ]] || die "--subscription <sandbox-sub-id> is required."

case "$ACTION" in
  exclude) TARGET_MG="${PREFIX}-sandbox-excluded" ;;
  restore) TARGET_MG="${PREFIX}-sandbox" ;;
  *) die "First argument must be 'exclude' or 'restore'." ;;
esac

_bold "Moving sandbox subscription into MG '$TARGET_MG' (S9)"
az account management-group subscription add \
  --name "$TARGET_MG" --subscription "$SUB" --only-show-errors >/dev/null
changed "subscription $SUB now under $TARGET_MG"
log "Allow several minutes + 2–3 cycles for Resource Graph to reflect the move."
if [[ "$ACTION" == "exclude" ]]; then
  log "Expect W10 to DISAPPEAR from decision records while excluded."
else
  log "Expect W10 to RETURN to decision records after the move settles."
fi
