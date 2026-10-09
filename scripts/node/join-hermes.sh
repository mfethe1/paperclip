#!/usr/bin/env bash
# Join this host's Hermes gateway to the Paperclip board as a hermes_gateway agent.
# Uses only curl + jq (no Node needed on the host).
#
# Step 1 (request):  API_SERVER_KEY=... scripts/node/join-hermes.sh request \
#                       --paperclip https://<mack>.<tailnet>.ts.net:3100 \
#                       --invite <invite-token> --name "Hermes (Rosie)" [--api-base-url URL]
#   The board then approves it (UI, or: paperclipai join approve <request-id> -C <company-id>).
# Step 2 (claim):    scripts/node/join-hermes.sh claim --paperclip https://...:3100 --request <request-id>
#
# The one-time claim secret and the claimed agent key are written 0600 under
# ~/.config/paperclip-fleet/ and never printed. API_SERVER_KEY comes from the
# environment so it stays out of shell history and process listings.
set -euo pipefail
# shellcheck source=../lib/common.sh
source "$(dirname "$0")/../lib/common.sh"

action="${1:-}"; shift || true
paperclip=""; invite=""; name=""; request=""; api_base_url=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --paperclip) paperclip="${2%/}"; shift 2 ;;
    --invite) invite="$2"; shift 2 ;;
    --name) name="$2"; shift 2 ;;
    --request) request="$2"; shift 2 ;;
    --api-base-url) api_base_url="${2%/}"; shift 2 ;;
    -h|--help) sed -n '2,14p' "$0"; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
done
need curl
need jq
[[ -n "$paperclip" ]] || die "--paperclip <board URL> is required"
STATE_DIR="$HOME/.config/paperclip-fleet"
mkdir -p "$STATE_DIR"
chmod 700 "$STATE_DIR"
umask 077

case "$action" in
  request)
    [[ -n "$invite" && -n "$name" ]] || die "request needs --invite and --name"
    [[ -n "${API_SERVER_KEY:-}" ]] || die "export API_SERVER_KEY (the value this host's Hermes API server runs with)"
    export API_SERVER_KEY
    if [[ -z "$api_base_url" ]]; then
      api_base_url="https://$(tailnet_fqdn):${HERMES_GATEWAY_PORT}"
    fi
    [[ "$api_base_url" == https://* ]] \
      || die "Paperclip refuses plain-HTTP remote Hermes URLs; publish it first: scripts/node/expose-gateway.sh hermes"
    code="$(http_code "$api_base_url/health")"
    [[ "$code" == "200" ]] || die "$api_base_url/health returned HTTP $code; is the gateway published?"

    payload="$(jq -n --arg name "$name" --arg url "$api_base_url" --arg pc "$paperclip" \
      --arg host "$(hostname -s 2>/dev/null || hostname)" '{
        requestType: "agent",
        agentName: $name,
        adapterType: "hermes_gateway",
        capabilities: ("Hermes gateway on " + $host),
        agentDefaultsPayload: {apiBaseUrl: $url, paperclipApiUrl: $pc, sessionKeyStrategy: "issue"}
      }' | jq '.agentDefaultsPayload.apiKey = env.API_SERVER_KEY')"   # via env, not argv (ps-visible)
    resp="$(mktemp)"
    http="$(curl -sS -o "$resp" -w '%{http_code}' -X POST -H 'content-type: application/json' \
      --data-binary @- "$paperclip/api/invites/$invite/accept" <<<"$payload")"
    [[ "$http" == 2* ]] || { jq -c '{error, details}' "$resp" 2>/dev/null >&2 || true; rm -f "$resp"; die "join request failed (HTTP $http)"; }
    id="$(jq -r '.id' "$resp")"
    jq '{id, claimSecret, companyId, agentName}' "$resp" > "$STATE_DIR/join-$id.json"
    jq -r '.diagnostics[]? | "  [\(.level)] \(.message)"' "$resp"
    rm -f "$resp"
    log "join request $id submitted (status pending_approval); claim secret saved to $STATE_DIR/join-$id.json"
    log "board: approve it, then run: $0 claim --paperclip $paperclip --request $id"
    ;;
  claim)
    [[ -n "$request" ]] || die "claim needs --request <request-id>"
    f="$STATE_DIR/join-$request.json"
    [[ -f "$f" ]] || die "no saved claim secret at $f (was the request made from this host?)"
    resp="$(mktemp)"
    http="$(jq '{claimSecret}' "$f" | curl -sS -o "$resp" -w '%{http_code}' -X POST \
      -H 'content-type: application/json' --data-binary @- \
      "$paperclip/api/join-requests/$request/claim-api-key")"
    [[ "$http" == 2* ]] || { rm -f "$resp"; die "claim failed (HTTP $http); is the request approved, and not already claimed?"; }
    agent="$(jq -r '.agentId' "$resp")"
    jq '{agentId, keyId, token, createdAt}' "$resp" > "$STATE_DIR/agent-key-$agent.json"
    rm -f "$resp" "$f"
    log "agent $agent key saved to $STATE_DIR/agent-key-$agent.json (0600); the claim secret file was removed"
    log "next on the board: set this agent's reportsTo and title, then give it a smoke issue (docs/RUNBOOK.md)"
    ;;
  *)
    die "usage: $0 request|claim ... (see --help)"
    ;;
esac
