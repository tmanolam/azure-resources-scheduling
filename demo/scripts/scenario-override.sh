#!/usr/bin/env bash
#
# DM-40 — Set or clear a schedule override on a resource, resource group or
# subscription (scenarios S4 "work late", S5 "stop early", S5b "ad-hoc start",
# S14 "subscription override for the cap test").
#
# Usage:
#   scenario-override.sh set   --target <resource-id> --state running|stopped [--hours N]
#   scenario-override.sh clear --target <resource-id>
#
#   <resource-id> is any Azure resource id: a resource, a resource group
#   (/subscriptions/.../resourceGroups/<rg>), or a subscription
#   (/subscriptions/<id>). Overrides on a RG/subscription apply to every tagged
#   resource inside it.
#
# Idempotent: re-setting the same tags is a no-op in effect; clearing already-
# absent tags is harmless. Prints what it changed.

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/common.sh"
require_az

ACTION="${1:-}"; shift || true
TARGET=""; STATE="running"; HOURS=4

while [[ $# -gt 0 ]]; do
  case "$1" in
    --target) TARGET="$2"; shift 2 ;;
    --state)  STATE="$2";  shift 2 ;;
    --hours)  HOURS="$2";  shift 2 ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    *) die "Unknown argument: $1" ;;
  esac
done

[[ -n "$TARGET" ]] || die "--target <resource-id> is required."

case "$ACTION" in
  set)
    [[ "$STATE" == "running" || "$STATE" == "stopped" ]] || die "--state must be running or stopped."
    UNTIL="$(until_bangkok_hours "$HOURS")"
    _bold "Setting override on $TARGET"
    log "state = $STATE, until = $UNTIL (Asia/Bangkok)"
    az tag update --operation Merge --resource-id "$TARGET" \
      --tags "schedule-override-state=$STATE" "schedule-override-until=$UNTIL" \
      --only-show-errors >/dev/null
    changed "schedule-override-state=$STATE, schedule-override-until=$UNTIL"
    log "The next cycle (≤ 15 min) will apply it; the schedule resumes after $UNTIL."
    ;;
  clear)
    _bold "Clearing override on $TARGET"
    az tag update --operation Delete --resource-id "$TARGET" \
      --tags schedule-override-state schedule-override-until \
      --only-show-errors >/dev/null 2>&1 \
      && changed "removed schedule-override-state / schedule-override-until" \
      || noop "override tags were not present"
    ;;
  *)
    die "First argument must be 'set' or 'clear'. See --help."
    ;;
esac
