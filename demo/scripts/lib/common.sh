#!/usr/bin/env bash
# Shared helpers for the demo scenario scripts (DM-40). Source, don't execute.
#
#   source "$(dirname "$0")/lib/common.sh"
#
# Provides: logging, az presence check, resource-group id helpers, and a
# consistent "what changed" print convention. All scenario scripts are
# idempotent and print exactly what they changed.

set -euo pipefail

# --- logging ----------------------------------------------------------------
_bold() { printf '\033[1m%s\033[0m\n' "$*"; }
log()    { printf '  %s\n' "$*"; }
changed(){ printf '  CHANGED: %s\n' "$*"; }
noop()   { printf '  (no change) %s\n' "$*"; }
die()    { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

# --- preconditions ----------------------------------------------------------
require_az() {
  command -v az >/dev/null || die "Azure CLI (az) is required."
}

# Compute a resource-group resource id from a subscription + RG name.
rg_id() {
  local sub="$1" rg="$2"
  echo "/subscriptions/${sub}/resourceGroups/${rg}"
}

# Compute an ISO-8601 "until" timestamp N hours from now in Asia/Bangkok (+07:00).
# GNU date and BSD/macOS date differ; handle both.
until_bangkok_hours() {
  local hours="$1"
  if date -v+1H >/dev/null 2>&1; then
    TZ=Asia/Bangkok date -v+"${hours}"H +%Y-%m-%dT%H:%M+07:00   # BSD/macOS
  else
    TZ=Asia/Bangkok date -d "+${hours} hours" +%Y-%m-%dT%H:%M+07:00  # GNU
  fi
}
