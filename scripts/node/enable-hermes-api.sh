#!/usr/bin/env bash
# Turn on the API server of this host's main Hermes gateway, so Paperclip can send
# it work (hermes_gateway adapter). Run on the Hermes host (Mack) as the user that
# runs Hermes.
#
# Sets, in $HERMES_HOME/.env (default ~/.hermes/.env, backed up first):
#   API_SERVER_ENABLED=true
#   API_SERVER_HOST=127.0.0.1   loopback only; Tailscale Serve publishes it (expose-gateway.sh)
#   API_SERVER_PORT=8642        unless one is already set
#   API_SERVER_KEY=<random>     only if none is set; never printed
#
# Then restarts the gateway (--restart; macOS launchd job ai.hermes.gateway), waits
# for /health, and checks that /v1/capabilities refuses a request without the key.
# Restarting interrupts in-flight Hermes chats and cron runs for a few seconds;
# pick a quiet moment.
#
# Usage: scripts/node/enable-hermes-api.sh [--restart] [--dry-run]
#        scripts/node/enable-hermes-api.sh --off [--restart]    # API_SERVER_ENABLED=false
set -euo pipefail
# shellcheck source=../lib/common.sh
source "$(dirname "$0")/../lib/common.sh"

RESTART=0; OFF=0; DRY=0
LABEL="${HERMES_LAUNCHD_LABEL:-ai.hermes.gateway}"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --restart) RESTART=1; shift ;;
    --off) OFF=1; shift ;;
    --dry-run) DRY=1; shift ;;
    -h|--help) sed -n '2,18p' "$0"; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
done
need curl

HH="$(hermes_home)"
ENVF="$HH/.env"
[[ -d "$HH" ]] || die "no Hermes home at $HH (set HERMES_HOME if Hermes uses another one)"
command -v hermes >/dev/null 2>&1 && log "hermes: $(hermes --version 2>/dev/null | head -1 || echo 'version unknown')"

# A key set in the launchd job's own environment hides problems: say so.
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
if [[ -f "$PLIST" ]] && grep -q 'API_SERVER_' "$PLIST"; then
  warn "$PLIST sets API_SERVER_* itself. Hermes 0.19+ lets ~/.hermes/.env win; older versions may not. Remove them from the plist if the result below disagrees."
fi

restart_gateway() {
  if [[ "$(uname -s)" == "Darwin" ]] && launchctl print "gui/$(id -u)/$LABEL" >/dev/null 2>&1; then
    if [[ "$RESTART" == "1" ]]; then
      run launchctl kickstart -k "gui/$(id -u)/$LABEL"
    else
      log "restart Hermes to apply: launchctl kickstart -k gui/$(id -u)/$LABEL   (or re-run with --restart)"
      return 1
    fi
  else
    log "restart the Hermes gateway the way this host runs it (no launchd job '$LABEL' found)"
    return 1
  fi
}

if [[ "$OFF" == "1" ]]; then
  [[ "$DRY" == "1" ]] && { log "[dry-run] would set API_SERVER_ENABLED=false in $ENVF"; exit 0; }
  dotenv_backup "$ENVF"
  dotenv_set "$ENVF" API_SERVER_ENABLED <<<"false"
  log "API_SERVER_ENABLED=false written; the key is kept so a re-enable doesn't break the board's stored copy"
  restart_gateway || true
  exit 0
fi

PORT="$(dotenv_get "$ENVF" API_SERVER_PORT)"; PORT="${PORT:-$HERMES_GATEWAY_PORT}"
HAVE_KEY=0; [[ -n "$(dotenv_get "$ENVF" API_SERVER_KEY)" ]] && HAVE_KEY=1
HOSTV="$(dotenv_get "$ENVF" API_SERVER_HOST)"
if [[ -n "$HOSTV" && "$HOSTV" != "127.0.0.1" && "$HOSTV" != "localhost" ]]; then
  warn "API_SERVER_HOST is '$HOSTV'; resetting it to 127.0.0.1 (Tailscale Serve publishes it instead)"
fi
if [[ "$DRY" == "1" ]]; then
  log "[dry-run] would set in $ENVF: API_SERVER_ENABLED=true, API_SERVER_HOST=127.0.0.1, API_SERVER_PORT=$PORT$([[ $HAVE_KEY == 1 ]] && echo ', keep the existing API_SERVER_KEY' || echo ', a new random API_SERVER_KEY')"
  exit 0
fi

dotenv_backup "$ENVF"
dotenv_set "$ENVF" API_SERVER_ENABLED <<<"true"
dotenv_set "$ENVF" API_SERVER_HOST <<<"127.0.0.1"
dotenv_set "$ENVF" API_SERVER_PORT <<<"$PORT"
if [[ "$HAVE_KEY" == "0" ]]; then
  need openssl
  openssl rand -hex 32 | dotenv_set "$ENVF" API_SERVER_KEY
  log "generated a new API_SERVER_KEY in $ENVF (not printed)"
else
  log "kept the existing API_SERVER_KEY"
fi

restart_gateway || exit 0
log "waiting for the API server on 127.0.0.1:$PORT"
for _ in $(seq 1 30); do
  [[ "$(http_code "http://127.0.0.1:$PORT/health" 3)" == "200" ]] && break
  sleep 2
done
code="$(http_code "http://127.0.0.1:$PORT/health" 3)"
[[ "$code" == "200" ]] || die "no /health on 127.0.0.1:$PORT after restart (HTTP $code); check the gateway log, or roll back with: $0 --off --restart"
assert_requires_auth "http://127.0.0.1:$PORT/v1/capabilities"
log "Hermes API server is up on 127.0.0.1:$PORT and requires its key"
log "next: scripts/node/expose-gateway.sh hermes   (publishes it to the tailnet over HTTPS)"
