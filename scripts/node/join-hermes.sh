#!/usr/bin/env bash
# Join this host's Hermes gateway to the Paperclip board as a hermes_gateway agent.
# Uses only curl + jq (no Node needed on the host).
#
# Step 1 (request):  scripts/node/join-hermes.sh request \
#                       --paperclip https://<board-host>.<tailnet>.ts.net:3100 \
#                       --invite <invite-token> --name "Hermes (Mack)" [--api-base-url URL]
#   The board then approves it (UI, or: paperclipai join approve <request-id> -C <company-id>).
# Step 2 (claim):    scripts/node/join-hermes.sh claim --paperclip https://...:3100 --request <request-id>
#                       [--no-hermes-install] [--restart]
#
# API_SERVER_KEY is taken from the environment, or else from ~/.hermes/.env (where
# enable-hermes-api.sh put it); it never appears in argv or output.
# The one-time claim secret and the claimed agent key are written 0600 under
# ~/.config/paperclip-fleet/ and never printed.
#
# Claim also sets Hermes up to work the board (skip with --no-hermes-install):
#   - ~/.hermes/.env gets PAPERCLIP_API_URL, PAPERCLIP_API_KEY (the claimed key),
#     PAPERCLIP_COMPANY_ID and PAPERCLIP_AGENT_ID (backed up first). Paperclip's
#     wake tells Hermes to update the issue itself; without a key it can't.
#   - ~/.hermes/skills/paperclip: the board's own Paperclip skill (GET /api/skills/paperclip)
#   - ~/.hermes/skills/paperclip-fleet: this repo's skill (filing from chat, status,
#     verified status updates)
# Hermes picks these up after a gateway restart (--restart on macOS launchd).
set -euo pipefail
# shellcheck source=../lib/common.sh
source "$(dirname "$0")/../lib/common.sh"

action="${1:-}"; shift || true
case "$action" in -h|--help|"") sed -n '2,24p' "$0"; exit 0 ;; esac
paperclip=""; invite=""; name=""; request=""; api_base_url=""; hermes_install=1; restart=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --paperclip) paperclip="${2%/}"; shift 2 ;;
    --invite) invite="$2"; shift 2 ;;
    --name) name="$2"; shift 2 ;;
    --request) request="$2"; shift 2 ;;
    --api-base-url) api_base_url="${2%/}"; shift 2 ;;
    --no-hermes-install) hermes_install=0; shift ;;
    --restart) restart=1; shift ;;
    -h|--help) sed -n '2,24p' "$0"; exit 0 ;;
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

# Give Hermes the claimed key and the skills it needs to work the board.
install_into_hermes() {
  local agent="$1" company="$2" hh envf skill_src tmp code
  hh="$(hermes_home)"; envf="$hh/.env"
  [[ -d "$hh" ]] || { warn "no Hermes home at $hh; skipped installing the key and skills into Hermes"; return 0; }
  [[ -n "$company" ]] || die "the saved join request has no companyId; re-run claim with --no-hermes-install and set PAPERCLIP_* in $envf by hand"
  dotenv_backup "$envf"
  local key_file="$STATE_DIR/agent-key-$agent.json"
  dotenv_set "$envf" PAPERCLIP_API_URL <<<"$paperclip"
  jq -r '.token' "$key_file" | dotenv_set "$envf" PAPERCLIP_API_KEY
  dotenv_set "$envf" PAPERCLIP_COMPANY_ID <<<"$company"
  dotenv_set "$envf" PAPERCLIP_AGENT_ID <<<"$agent"
  log "wrote PAPERCLIP_API_URL, PAPERCLIP_API_KEY (not printed), PAPERCLIP_COMPANY_ID, PAPERCLIP_AGENT_ID to $envf"

  mkdir -p "$hh/skills/paperclip"
  tmp="$(mktemp)"
  # The key goes to curl through a header file on stdin, never argv.
  code="$(jq -r '"authorization: Bearer " + .token' "$key_file" \
    | curl -sS -m 30 -o "$tmp" -w '%{http_code}' -H @- "$paperclip/api/skills/paperclip" || true)"
  if [[ "$code" == "200" ]] && head -1 "$tmp" | grep -q '^---'; then
    cp "$tmp" "$hh/skills/paperclip/SKILL.md"
    log "installed the board's Paperclip skill to $hh/skills/paperclip"
  else
    warn "could not fetch the Paperclip skill from the board (HTTP ${code:-000}); Hermes still has paperclip-fleet"
  fi
  rm -f "$tmp"
  skill_src="$REPO_ROOT/hermes/skills/paperclip-fleet"
  rm -rf "$hh/skills/paperclip-fleet"
  cp -R "$skill_src" "$hh/skills/paperclip-fleet"
  chmod +x "$hh/skills/paperclip-fleet/scripts/"*.sh
  log "installed the paperclip-fleet skill to $hh/skills/paperclip-fleet"

  local label="${HERMES_LAUNCHD_LABEL:-ai.hermes.gateway}"
  if [[ "$restart" == "1" && "$(uname -s)" == "Darwin" ]] && launchctl print "gui/$(id -u)/$label" >/dev/null 2>&1; then
    run launchctl kickstart -k "gui/$(id -u)/$label"
    log "restarted $label"
  else
    log "restart Hermes so it loads the key and skills: launchctl kickstart -k gui/$(id -u)/$label"
  fi
}

case "$action" in
  request)
    [[ -n "$invite" && -n "$name" ]] || die "request needs --invite and --name"
    if [[ -z "${API_SERVER_KEY:-}" ]]; then
      API_SERVER_KEY="$(dotenv_get "$(hermes_home)/.env" API_SERVER_KEY)"
    fi
    [[ -n "${API_SERVER_KEY:-}" ]] || die "no API_SERVER_KEY in the environment or $(hermes_home)/.env; run scripts/node/enable-hermes-api.sh first"
    export API_SERVER_KEY
    if [[ -z "$api_base_url" ]]; then
      api_base_url="https://$(tailnet_fqdn):${HERMES_GATEWAY_PORT}"
    fi
    # Paperclip accepts plain HTTP only on loopback (Hermes on the board host itself).
    [[ "$api_base_url" == https://* || "$api_base_url" =~ ^http://(127\.0\.0\.1|localhost)(:[0-9]+)?$ ]] \
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
    company="$(jq -r '.companyId // empty' "$f")"
    jq '{agentId, keyId, token, createdAt}' "$resp" > "$STATE_DIR/agent-key-$agent.json"
    rm -f "$resp" "$f"
    log "agent $agent key saved to $STATE_DIR/agent-key-$agent.json (0600); the claim secret file was removed"
    if [[ "$hermes_install" == "1" ]]; then
      install_into_hermes "$agent" "$company"
    fi
    log "next on the board: set this agent's reportsTo and title, then give it a smoke issue (docs/RUNBOOK.md)"
    ;;
  *)
    die "usage: $0 request|claim ... (see --help)"
    ;;
esac
