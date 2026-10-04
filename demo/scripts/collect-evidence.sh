#!/usr/bin/env bash
#
# DM-42 — collect-evidence.sh <label>
#
# Runs the VERIFICATION §3.4 queries (1–7) and the §8 demo queries (Q-A..Q-G)
# against the deployed Application Insights, saving each result to
#   demo/evidence/<date>-<label>/
# so the output can be linked from the VERIFICATION §6 results log.
#
# The evidence directory is git-ignored (see demo/.gitignore).
#
# Usage:
#   collect-evidence.sh <label> [--app <appi-name>] [--rg <rg>]
#
# If --app/--rg are omitted, they are read from the infra/scheduler Terraform
# outputs (application_insights_name, resource_group_name).

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/common.sh"
require_az

LABEL="${1:-}"; shift || true
[[ -n "$LABEL" ]] || die "Usage: collect-evidence.sh <label> [--app <appi>] [--rg <rg>]"

APPI=""; RG=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --app) APPI="$2"; shift 2 ;;
    --rg)  RG="$2"; shift 2 ;;
    *) die "Unknown argument: $1" ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
QUERIES_DIR="$REPO_ROOT/demo/queries"

# DR-14: resolve App Insights name + RG from the DEMO scheduler outputs. Use the
# per-tenant wrapper so the DEMO backend is (re)initialised first — a bare
# `terraform -chdir=infra/scheduler output` would read whatever backend that
# folder was last initialised with (possibly another tenant), pointing the
# evidence queries at the wrong Application Insights.
if [[ -z "$APPI" || -z "$RG" ]]; then
  if [[ -x "$REPO_ROOT/infra/deploy.sh" ]]; then
    DEMO_OUT="$("$REPO_ROOT/infra/deploy.sh" demo output 2>/dev/null || true)"
    # deploy.sh demo output prints `name = "value"` lines; extract the two we need.
    [[ -z "$APPI" ]] && APPI="$(sed -n 's/^application_insights_name *= *"\(.*\)"$/\1/p' <<<"$DEMO_OUT" | head -1)"
    [[ -z "$RG" ]]   && RG="$(sed -n 's/^resource_group_name *= *"\(.*\)"$/\1/p' <<<"$DEMO_OUT" | head -1)"
  fi
fi
[[ -n "$APPI" && -n "$RG" ]] || die "Could not resolve App Insights/RG. Pass --app and --rg (or ensure ./infra/deploy.sh demo output works)."

OUT_DIR="$REPO_ROOT/demo/evidence/$(date +%Y-%m-%d)-$LABEL"
mkdir -p "$OUT_DIR"
_bold "Collecting evidence into $OUT_DIR (app=$APPI, rg=$RG)"

run_query() {
  local name="$1" kql="$2" out="$OUT_DIR/$name"
  log "running $name ..."
  if az monitor app-insights query --app "$APPI" --resource-group "$RG" \
       --analytics-query "$kql" -o table > "$out.txt" 2> "$out.err"; then
    rm -f "$out.err"
  else
    log "  WARN: $name failed; see $out.err"
  fi
}

# --- §8 demo queries (one .kql file each) -----------------------------------
# The §8 files are single queries; feed each straight to App Insights.
for f in "$QUERIES_DIR"/Q-*.kql; do
  [[ -e "$f" ]] || continue
  name="$(basename "$f" .kql)"
  # Strip // comment lines so the saved query runs cleanly; keep the rest.
  kql="$(grep -v -E '^\s*//' "$f")"
  [[ -n "${kql// /}" ]] && run_query "$name" "$kql"
done

# --- VERIFICATION §3.4 Queries 1–7 ------------------------------------------
# These live as a semicolon-separated multi-statement file; split on ';' at the
# end of a line into numbered single statements.
VERIFY_FILE="$QUERIES_DIR/verification-3.4-queries.kql"
if [[ -f "$VERIFY_FILE" ]]; then
  awk 'BEGIN{n=0; buf=""}
       /^\s*\/\//{next}
       {buf=buf $0 "\n"}
       /;\s*$/{n++; printf "%s", buf > ("/tmp/vq_" n ".kql"); buf=""}' "$VERIFY_FILE"
  i=1
  while [[ -f "/tmp/vq_$i.kql" ]]; do
    kql="$(sed 's/;\s*$//' "/tmp/vq_$i.kql")"
    [[ -n "${kql// /}" ]] && run_query "verification-query-$i" "$kql"
    rm -f "/tmp/vq_$i.kql"
    i=$((i+1))
  done
fi

_bold "Done."
log "Evidence saved under $OUT_DIR"
log "Link the relevant files from the VERIFICATION §6 results log."
