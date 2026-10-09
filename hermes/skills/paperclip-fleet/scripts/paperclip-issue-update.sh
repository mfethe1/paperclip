#!/usr/bin/env bash
# Change a Paperclip issue's status, with an optional comment read from stdin, and
# confirm the write. Exits 0 only when the board echoes the new status back.
# With a run id it first checks the issue out to that run (Paperclip only accepts
# agent writes from the run that holds the checkout). Agent writes need a run id:
# outside a Paperclip run, the board refuses them (403).
#
# Usage: paperclip-issue-update.sh --issue-id <id or key, e.g. FLE-12> --status <status>
#          [--run-id <Run ID from the Paperclip wake prompt>]
#          [--unblock-action "<what would unblock it>"]   # with --status blocked: owner is the board
#          [--comment - < comment.md | --comment "<text>"]
# Status: backlog | todo | in_progress | in_review | done | blocked | cancelled
# Env: PAPERCLIP_API_URL (board base URL, no /api), PAPERCLIP_API_KEY
set -euo pipefail
die() { printf 'error: %s\n' "$*" >&2; exit 1; }
command -v curl >/dev/null || die "curl is required"
command -v jq >/dev/null || die "jq is required"

issue=""; status=""; run_id="${PAPERCLIP_RUN_ID:-}"; unblock=""; body_text=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --issue-id) issue="$2"; shift 2 ;;
    --status) status="$2"; shift 2 ;;
    --run-id) run_id="$2"; shift 2 ;;
    --unblock-action) unblock="$2"; shift 2 ;;
    --comment) if [[ "$2" == "-" ]]; then body_text="$(cat)"; else body_text="$2"; fi; shift 2 ;;
    -h|--help) sed -n '2,13p' "$0"; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
done
: "${PAPERCLIP_API_URL:?PAPERCLIP_API_URL is not set (see ~/.hermes/.env)}"
: "${PAPERCLIP_API_KEY:?PAPERCLIP_API_KEY is not set (see ~/.hermes/.env)}"
[[ -n "$issue" && -n "$status" ]] || die "--issue-id and --status are required"
case "$status" in backlog|todo|in_progress|in_review|done|blocked|cancelled) ;; *) die "unknown status: $status" ;; esac

payload="$(jq -n --arg s "$status" --arg c "$body_text" --arg u "$unblock" '
  {status: $s}
  + (if $c != "" then {comment: $c} else {} end)
  + (if $s == "blocked" and $u != "" then {unblockDescriptor: {owner: "board", action: $u}} else {} end)')"

base="${PAPERCLIP_API_URL%/}"; base="${base%/api}"
hdr="$(mktemp)"; out="$(mktemp)"; trap 'rm -f "$hdr" "$out"' EXIT
chmod 600 "$hdr"; printf 'authorization: Bearer %s\n' "$PAPERCLIP_API_KEY" > "$hdr"   # not argv
hdrs=(-H "@$hdr" -H 'content-type: application/json')
if [[ -n "$run_id" ]]; then hdrs+=(-H "X-Paperclip-Run-Id: $run_id"); fi

# Retries only connection-level failures (DNS, refused, timeout, reset).
code=""; rc=0
send() { # method path body -> sets code and rc
  local attempt
  for attempt in 1 2 3; do
    rc=0
    code="$(curl -sS -m 30 -o "$out" -w '%{http_code}' -X "$1" "${hdrs[@]}" \
      --data-binary @- "$base$2" <<<"$3")" || rc=$?
    case "$rc" in
      0) return 0 ;;
      6|7|28|35|52|56) sleep $((attempt * 2)) ;;
      *) die "curl failed (exit $rc); the update was NOT confirmed" ;;
    esac
  done
  die "board unreachable after 3 attempts; the update was NOT confirmed"
}

if [[ -n "$run_id" && -n "${PAPERCLIP_AGENT_ID:-}" ]]; then
  checkout="$(jq -n --arg a "$PAPERCLIP_AGENT_ID" \
    '{agentId: $a, expectedStatuses: ["backlog", "todo", "in_progress", "in_review", "blocked"]}')"
  send POST "/api/issues/$issue/checkout" "$checkout"
  [[ "$code" == "200" ]] || die "checkout failed, HTTP $code: $(jq -c '{error, details}' "$out" 2>/dev/null || head -c 300 "$out"); the update was NOT made"
fi

send PATCH "/api/issues/$issue" "$payload"
if [[ "$code" != "200" ]]; then
  die "HTTP $code: $(jq -c '{error, details}' "$out" 2>/dev/null || head -c 300 "$out")"
fi
got="$(jq -r '.status // empty' "$out")"
[[ "$got" == "$status" ]] || die "board answered but the status is '$got', not '$status'; the update was NOT confirmed"
printf '%s is now %s\n' "$(jq -r '.identifier // .id' "$out")" "$got"
