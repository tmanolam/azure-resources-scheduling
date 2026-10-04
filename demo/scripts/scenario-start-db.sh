#!/usr/bin/env bash
#
# DM-40 — Manually start a database to create drift (scenario S10). Out of
# business hours, start W7 (PostgreSQL Flexible); the next cycle should stop it
# again (models the 7-day platform auto-restart too).
#
# Usage:
#   scenario-start-db.sh --subscription <dev-sub-id> [--rg rg-demo-db] [--name psql-demo-w7]
#                        [--kind postgres|mysql]

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/common.sh"
require_az

SUB=""; RG="rg-demo-db"; NAME="psql-demo-w7"; KIND="postgres"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --subscription) SUB="$2"; shift 2 ;;
    --rg)           RG="$2"; shift 2 ;;
    --name)         NAME="$2"; shift 2 ;;
    --kind)         KIND="$2"; shift 2 ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) die "Unknown argument: $1" ;;
  esac
done
[[ -n "$SUB" ]] || die "--subscription <dev-sub-id> is required."

az account set --subscription "$SUB"

case "$KIND" in
  postgres) grp="postgres flexible-server" ;;
  mysql)    grp="mysql flexible-server" ;;
  *) die "--kind must be postgres or mysql" ;;
esac

_bold "Checking current state of $NAME ($KIND) in $RG"
state="$(az $grp show -g "$RG" -n "$NAME" --query state -o tsv 2>/dev/null || echo "Unknown")"
log "current state = $state"

if [[ "$state" == "Ready" || "$state" == "Started" || "$state" == "Running" ]]; then
  noop "$NAME is already running; drift test needs it started out of hours only"
  exit 0
fi

_bold "Starting $NAME to create drift (S10)"
# shellcheck disable=SC2086
az $grp start -g "$RG" -n "$NAME" --only-show-errors >/dev/null
changed "$NAME start submitted — expect the next cycle to stop it again"
