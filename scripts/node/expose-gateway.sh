#!/usr/bin/env bash
# Publish this host's agent gateway to the tailnet over HTTPS so the Paperclip
# control plane can reach it, then print the URL to use when the agent joins.
#
#   hermes   : Hermes API server, expected on 127.0.0.1:8642 (API_SERVER_ENABLED=true,
#              API_SERVER_KEY set). Paperclip refuses plain-HTTP remote Hermes URLs,
#              so Tailscale Serve provides HTTPS with a real cert.
#   openclaw : OpenClaw gateway, expected on 127.0.0.1:18789. If Tailscale Serve
#              already fronts it (Rosie: :443), that mapping is reused.
#
# Safe to re-run. Never touches a Serve port that already proxies elsewhere, and
# refuses to publish a gateway that answers without credentials.
#
# Usage: scripts/node/expose-gateway.sh hermes|openclaw [--port N] [--dry-run]
set -euo pipefail
# shellcheck source=../lib/common.sh
source "$(dirname "$0")/../lib/common.sh"

kind="${1:-}"; shift || true
port=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --port) port="$2"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) sed -n '2,15p' "$0"; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
done
export DRY_RUN="${DRY_RUN:-0}"
need curl
need jq
TS="$(tailscale_bin)"
FQDN="$(tailnet_fqdn)"

# Existing Serve port (if any) that already proxies to 127.0.0.1:<target>.
serve_port_for_target() {
  "$TS" serve status --json 2>/dev/null | jq -r --arg fqdn "$FQDN" --arg t "http://127.0.0.1:$1" '
    (.Web // {}) | to_entries[]
    | select(.key | startswith($fqdn + ":"))
    | select([.value.Handlers[]?.Proxy] | index($t))
    | .key | split(":")[1]' 2>/dev/null | head -1
}

listener_scope() {
  # Prints the address the local port is bound to, e.g. 127.0.0.1 or * / 0.0.0.0.
  if command -v lsof >/dev/null 2>&1; then
    lsof -nP -iTCP:"$1" -sTCP:LISTEN 2>/dev/null | awk 'NR>1 {split($9,a,":"); print a[1]; exit}'
  elif command -v ss >/dev/null 2>&1; then
    ss -ltnH "sport = :$1" 2>/dev/null | awk '{split($4,a,":"); print a[1]; exit}'
  fi
}

case "$kind" in
  hermes)
    target="$HERMES_GATEWAY_PORT"
    code="$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:${target}/health" || echo 000)"
    [[ "$code" == "200" ]] || die "Hermes API server not answering on 127.0.0.1:${target} (HTTP $code).
Start it with API_SERVER_ENABLED=true and API_SERVER_KEY set (see docs/RUNBOOK.md, 'Join a host: Hermes')."
    scope="$(listener_scope "$target" || true)"
    if [[ -n "$scope" && "$scope" != "127.0.0.1" && "$scope" != "localhost" ]]; then
      warn "Hermes is listening on '$scope', not loopback only. Bind it to 127.0.0.1; Serve provides tailnet access."
    fi
    [[ -n "$port" ]] || port="$(serve_port_for_target "$target")"
    [[ -n "$port" ]] || port="$target"
    serve_https "$port" "$target"
    url="https://${FQDN}:${port}"
    [[ "$port" == "443" ]] && url="https://${FQDN}"
    [[ "$DRY_RUN" == "1" ]] || assert_requires_auth "$url/v1/capabilities"
    cat <<EOF

Hermes gateway published.
  apiBaseUrl (give this to the Paperclip join request): $url
  apiKey: the value of API_SERVER_KEY on this host (do not paste it into issues or chat)
Next: docs/RUNBOOK.md, 'Join a host: Hermes'.
EOF
    ;;
  openclaw)
    target="$OPENCLAW_GATEWAY_PORT"
    code="$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:${target}/" || echo 000)"
    [[ "$code" != "000" ]] || die "OpenClaw gateway not listening on 127.0.0.1:${target}"
    cfg="$HOME/.openclaw/openclaw.json"
    if [[ -f "$cfg" ]]; then
      jq -e '((.gateway.auth.token // "") | length) >= 16 or ((.gateway.auth.password // "") | length) >= 12' "$cfg" >/dev/null \
        || die "OpenClaw gateway auth looks unset or weak in $cfg; set gateway.auth.token (>= 16 chars) first"
      log "OpenClaw gateway auth is configured (value not shown)"
    else
      warn "no $cfg; cannot confirm gateway auth is set"
    fi
    [[ -n "$port" ]] || port="$(serve_port_for_target "$target")"
    [[ -n "$port" ]] || port="$target"
    serve_https "$port" "$target"
    url="wss://${FQDN}:${port}"
    [[ "$port" == "443" ]] && url="wss://${FQDN}"
    cat <<EOF

OpenClaw gateway published.
  gateway URL for the openclaw_gateway agent: $url
Next: docs/RUNBOOK.md, 'Join a host: OpenClaw'. Generate the invite prompt in Paperclip
and paste it into this host's OpenClaw main chat.
EOF
    ;;
  *)
    die "usage: $0 hermes|openclaw [--port N] [--dry-run]"
    ;;
esac
