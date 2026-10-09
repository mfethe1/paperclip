#!/usr/bin/env bash
# File a request from chat as a Paperclip issue in Intake, assigned to the Chief of
# Staff for triage. Prints the new issue key.
#
# Usage: paperclip-intake.sh --title "<the outcome, one line>" [--priority low|medium|high|critical]
#          [--due YYYY-MM-DD] [--project Intake] [--dry-run]
#          [--description - < description.md | --description "<text>"]
# Env: PAPERCLIP_API_URL (board base URL, no /api), PAPERCLIP_API_KEY, PAPERCLIP_COMPANY_ID
set -euo pipefail
die() { printf 'error: %s\n' "$*" >&2; exit 1; }
command -v curl >/dev/null || die "curl is required"
command -v jq >/dev/null || die "jq is required"

title=""; priority="medium"; due=""; project="Intake"; dry=0; desc=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --title) title="$2"; shift 2 ;;
    --priority) priority="$2"; shift 2 ;;
    --due) due="$2"; shift 2 ;;
    --project) project="$2"; shift 2 ;;
    --dry-run) dry=1; shift ;;
    --description) if [[ "$2" == "-" ]]; then desc="$(cat)"; else desc="$2"; fi; shift 2 ;;
    -h|--help) sed -n '2,8p' "$0"; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
done
: "${PAPERCLIP_API_URL:?PAPERCLIP_API_URL is not set (see ~/.hermes/.env)}"
: "${PAPERCLIP_API_KEY:?PAPERCLIP_API_KEY is not set (see ~/.hermes/.env)}"
: "${PAPERCLIP_COMPANY_ID:?PAPERCLIP_COMPANY_ID is not set (see ~/.hermes/.env)}"
[[ -n "$title" ]] || die "--title is required"
case "$priority" in low|medium|high|critical) ;; *) die "--priority must be low, medium, high or critical" ;; esac
[[ -z "$due" || "$due" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] || die "--due takes YYYY-MM-DD"

base="${PAPERCLIP_API_URL%/}"; base="${base%/api}"
hdr="$(mktemp)"; out="$(mktemp)"; trap 'rm -f "$hdr" "$out"' EXIT
chmod 600 "$hdr"; printf 'authorization: Bearer %s\n' "$PAPERCLIP_API_KEY" > "$hdr"   # not argv
auth=(-H "@$hdr")
get() { # path -> body on stdout, or exit
  local code
  code="$(curl -sS -m 30 -o "$out" -w '%{http_code}' "${auth[@]}" "$base$1")" || die "board unreachable"
  [[ "$code" == "200" ]] || die "GET ${1%%\?*} -> HTTP $code"
  cat "$out"
}

co="$PAPERCLIP_COMPANY_ID"
project_id="$(get "/api/companies/$co/projects" | jq -r --arg n "$project" \
  '[.[] | select((.name | ascii_downcase) == ($n | ascii_downcase))][0].id // empty')"
[[ -n "$project_id" ]] || die "no project named '$project' on the board"

# The Chief of Staff (role ceo) triages Intake. If it can't run right now, leave the
# issue unassigned in backlog: Paperclip blocks todo work assigned to a paused agent.
agents="$(get "/api/companies/$co/agents")"
cos_id="$(jq -r '[.[] | select(.role == "ceo")][0].id // empty' <<<"$agents")"
cos_status="$(jq -r '[.[] | select(.role == "ceo")][0].status // empty' <<<"$agents")"
assign=1
case "$cos_status" in ""|paused|error|terminated|pending_approval) assign=0 ;; esac

# Same title already open? Point at it instead of filing a duplicate.
q="$(jq -rn --arg t "$title" '$t | @uri')"
dup="$(get "/api/companies/$co/issues?q=$q&status=backlog,todo,in_progress,in_review,blocked&limit=50" \
  | jq -r --arg t "$title" '[.[] | select((.title | ascii_downcase) == ($t | ascii_downcase))][0].identifier // empty')"
[[ -z "$dup" ]] || { printf '%s already exists (open); not filing a duplicate\n' "$dup"; exit 0; }

body="$(jq -n --arg title "$title" --arg desc "$desc" --arg due "$due" --arg pid "$project_id" \
  --arg prio "$priority" --arg cos "$cos_id" --argjson assign "$assign" '
  {
    title: $title,
    projectId: $pid,
    priority: $prio,
    status: (if $assign == 1 then "todo" else "backlog" end),
    description: ((if $due != "" then "Due: " + $due + "\n\n" else "" end)
                  + $desc + "\n\nFiled by Hermes from chat.")
  } + (if $assign == 1 then {assigneeAgentId: $cos} else {} end)')"

if [[ "$dry" == "1" ]]; then jq . <<<"$body"; exit 0; fi
code="$(curl -sS -m 30 -o "$out" -w '%{http_code}' -X POST "${auth[@]}" -H 'content-type: application/json' \
  --data-binary @- "$base/api/companies/$co/issues" <<<"$body")" || die "board unreachable; nothing was filed"
[[ "$code" == 2* ]] || die "HTTP $code: $(jq -c '{error, details}' "$out" 2>/dev/null || head -c 300 "$out")"
key="$(jq -r '.identifier // .id' "$out")"
if [[ "$assign" == "1" ]]; then
  printf '%s filed in %s for the Chief of Staff to triage\n' "$key" "$project"
else
  printf '%s filed in %s (backlog; the Chief of Staff is %s, so it was left unassigned)\n' "$key" "$project" "${cos_status:-missing}"
fi
