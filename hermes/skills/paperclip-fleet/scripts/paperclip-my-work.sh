#!/usr/bin/env bash
# List open Paperclip issues for an agent (default: this Hermes agent), oldest
# activity first. For "what's late or at risk" use the fleet repo's
# scripts/commitments.sh instead.
#
# Usage: paperclip-my-work.sh [--agent <agent-id>] [--all-open]
# Env: PAPERCLIP_API_URL, PAPERCLIP_API_KEY, PAPERCLIP_COMPANY_ID, PAPERCLIP_AGENT_ID
set -euo pipefail
die() { printf 'error: %s\n' "$*" >&2; exit 1; }
command -v curl >/dev/null || die "curl is required"
command -v jq >/dev/null || die "jq is required"
agent="${PAPERCLIP_AGENT_ID:-}"; all=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --agent) agent="$2"; shift 2 ;;
    --all-open) all=1; shift ;;
    -h|--help) sed -n '2,7p' "$0"; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
done
: "${PAPERCLIP_API_URL:?PAPERCLIP_API_URL is not set}"
: "${PAPERCLIP_API_KEY:?PAPERCLIP_API_KEY is not set}"
: "${PAPERCLIP_COMPANY_ID:?PAPERCLIP_COMPANY_ID is not set}"
base="${PAPERCLIP_API_URL%/}"; base="${base%/api}"
filter="status=backlog,todo,in_progress,in_review,blocked&limit=200"
if [[ "$all" == "0" ]]; then
  [[ -n "$agent" ]] || die "no agent id; set PAPERCLIP_AGENT_ID or pass --agent"
  filter="$filter&assigneeAgentId=$agent"
fi
hdr="$(mktemp)"; out="$(mktemp)"; trap 'rm -f "$hdr" "$out"' EXIT
chmod 600 "$hdr"; printf 'authorization: Bearer %s\n' "$PAPERCLIP_API_KEY" > "$hdr"   # not argv
code="$(curl -sS -m 30 -o "$out" -w '%{http_code}' -H "@$hdr" \
  "$base/api/companies/$PAPERCLIP_COMPANY_ID/issues?$filter")" || die "board unreachable"
[[ "$code" == "200" ]] || die "HTTP $code"
jq -r '
  sort_by(.lastActivityAt // .updatedAt)
  | if length == 0 then "No open issues."
    else .[] | "\(.identifier)\t\(.status)\t\(.priority)\t\(.title)" end' "$out"
