#!/usr/bin/env bash
#
# DM-40 — Break or restore the Function App's APP_CONFIG_ENDPOINT to force a
# cycle to throw, proving the OBS-003 cycle-exceptions alert fires (finding H2,
# VERIFICATION §5). Always restore afterwards.
#
# Usage:
#   scenario-appconfig-endpoint.sh break   --rg <rg> --app <func-app>
#   scenario-appconfig-endpoint.sh restore --rg <rg> --app <func-app> --endpoint https://appcs-...azconfig.io
#
# "break" points the app at an invalid endpoint; the next cycle fails and the
# cycle-exceptions alert should fire. "restore" sets the real endpoint back.

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/common.sh"
require_az

ACTION="${1:-}"; shift || true
RG=""; APP=""; ENDPOINT=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --rg)       RG="$2"; shift 2 ;;
    --app)      APP="$2"; shift 2 ;;
    --endpoint) ENDPOINT="$2"; shift 2 ;;
    -h|--help) sed -n '2,13p' "$0"; exit 0 ;;
    *) die "Unknown argument: $1" ;;
  esac
done
[[ -n "$RG" && -n "$APP" ]] || die "--rg and --app are required."

case "$ACTION" in
  break)
    _bold "Breaking APP_CONFIG_ENDPOINT on $APP (cycle-exceptions test, H2)"
    az functionapp config appsettings set -g "$RG" -n "$APP" \
      --settings APP_CONFIG_ENDPOINT=https://invalid.azconfig.io \
      --only-show-errors >/dev/null
    changed "APP_CONFIG_ENDPOINT=https://invalid.azconfig.io"
    log "After the next cycle, confirm the <prefix>-cycle-exceptions alert fires. Then restore."
    ;;
  restore)
    [[ -n "$ENDPOINT" ]] || die "--endpoint <real-appconfig-endpoint> is required for restore."
    _bold "Restoring APP_CONFIG_ENDPOINT on $APP"
    az functionapp config appsettings set -g "$RG" -n "$APP" \
      --settings "APP_CONFIG_ENDPOINT=$ENDPOINT" \
      --only-show-errors >/dev/null
    changed "APP_CONFIG_ENDPOINT=$ENDPOINT"
    log "Confirm the next cycle succeeds."
    ;;
  *) die "First argument must be 'break' or 'restore'." ;;
esac
