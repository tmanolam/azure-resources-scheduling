#!/usr/bin/env bash
#
# DM-40 — Stop the Function App for longer than one interval, then start it, to
# prove past-due recovery (FR-007, finding M4, scenarios S13/S16). After the
# restart, VERIFICATION §3.4 Query 5 should show a past-due run.
#
# Usage:
#   scenario-funcapp-restart.sh --rg <rg> --app <func-app> [--sleep 1200]
#
# Default sleep is 1200s (20 min) — longer than the 15-minute interval so the
# timer registers as past due on restart.

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/common.sh"
require_az

RG=""; APP=""; SLEEP=1200
while [[ $# -gt 0 ]]; do
  case "$1" in
    --rg)    RG="$2"; shift 2 ;;
    --app)   APP="$2"; shift 2 ;;
    --sleep) SLEEP="$2"; shift 2 ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) die "Unknown argument: $1" ;;
  esac
done
[[ -n "$RG" && -n "$APP" ]] || die "--rg and --app are required."

_bold "Past-due recovery test on $APP (M4 / S16)"
log "Stopping the Function App ..."
az functionapp stop -g "$RG" -n "$APP" --only-show-errors >/dev/null
changed "$APP stopped"

log "Sleeping ${SLEEP}s (> one 15-min interval) so the timer goes past due ..."
sleep "$SLEEP"

log "Starting the Function App ..."
az functionapp start -g "$RG" -n "$APP" --only-show-errors >/dev/null
changed "$APP started"
log "In ~5 min, run demo/queries/verification-3.4-queries.kql Query 5 to confirm the past-due run."
