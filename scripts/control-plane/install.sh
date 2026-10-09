#!/usr/bin/env bash
# Install or reconcile the fleet's Paperclip control plane on the always-on host (Mack).
#
# Result:
#   - paperclipai ${PAPERCLIP_VERSION} in the managed CLI store (~/.paperclip/cli)
#   - instance in authenticated/private mode, listening on 127.0.0.1:3100 only
#   - Tailscale Serve: https://<this-node>.<tailnet>.ts.net:3100 -> http://127.0.0.1:3100
#     (:443 is left alone; on Mack it belongs to peer-relay)
#   - background service (macOS LaunchAgent / systemd user unit)
#
# Idempotent. An existing instance is reconciled in place: config.json is backed up
# and only server/telemetry fields are changed. Data, DB and secrets are never touched.
#
# Node: Paperclip needs Node >= 24.11. The system default node is left alone; a
# side-by-side Node 24 (Homebrew node@24, nvm, fnm, volta, asdf, mise) is used for
# the install and pinned into Paperclip's launcher. --install-node runs
# `brew install node@24` (keg-only) when none is found.
#
# Usage: scripts/control-plane/install.sh [--dry-run] [--install-node] [--keep-telemetry]
set -euo pipefail
# shellcheck source=../lib/common.sh
source "$(dirname "$0")/../lib/common.sh"

KEEP_TELEMETRY=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    --keep-telemetry) KEEP_TELEMETRY=1 ;;
    --install-node) INSTALL_NODE=1 ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    *) die "unknown argument: $arg" ;;
  esac
done
export DRY_RUN="${DRY_RUN:-0}"

need jq
need curl
INSTALL_NODE="${INSTALL_NODE:-0}" ensure_node24
TS="$(tailscale_bin)"
"$TS" status >/dev/null 2>&1 || die "tailscale is not up on this host (run: tailscale up)"
FQDN="$(tailnet_fqdn)"
[[ -n "$FQDN" && "$FQDN" != "null" ]] || die "could not read this node's MagicDNS name; enable MagicDNS for the tailnet"
SHORT="${FQDN%%.*}"
log "control plane host: $FQDN"

# 1. Managed, pinned CLI install (atomic switch, keeps two rollbacks).
export PATH="$HOME/.local/bin:$PATH"   # managed shim location
if [[ "$(paperclip_cli_version)" != "$PAPERCLIP_VERSION" ]]; then
  log "installing paperclipai ${PAPERCLIP_VERSION} into the managed CLI store"
  # Runs under the Node 24 that ensure_node24 put first on PATH; the managed shim
  # (~/.local/bin/paperclipai) pins that Node for the CLI and the LaunchAgent.
  run npx -y "paperclipai@${PAPERCLIP_VERSION}" install --version "$PAPERCLIP_VERSION"
  export PATH="$HOME/.local/bin:$PATH"
fi
[[ "$DRY_RUN" == "1" ]] || [[ "$(paperclip_cli_version)" == "$PAPERCLIP_VERSION" ]] \
  || die "paperclipai on PATH ($(command -v paperclipai || echo none)) reports '$(paperclip_cli_version)', expected $PAPERCLIP_VERSION"

# 2. Instance config: create on first run, otherwise reconcile.
CONFIG="$(paperclip_config_path)"
if [[ ! -f "$CONFIG" ]]; then
  log "no instance at $CONFIG; onboarding (authenticated/private) and installing the service"
  # --bind tailnet selects authenticated/private; the service install stops onboard
  # from running a foreground server. Step 3 narrows the listener to loopback.
  run paperclipai onboard --yes --bind tailnet --install-service
else
  log "existing instance found at $CONFIG; reconciling (data untouched)"
fi

if [[ "$DRY_RUN" != "1" ]]; then
  [[ -f "$CONFIG" ]] || die "onboarding did not produce $CONFIG"
  backup="${CONFIG}.bak.$(date +%Y%m%d%H%M%S)"
  cp -p "$CONFIG" "$backup"
  tmp="$(mktemp)"
  jq --arg host "$FQDN" --arg short "$SHORT" --argjson port "$PAPERCLIP_PORT" \
     --argjson keepTelemetry "$KEEP_TELEMETRY" '
    .server.deploymentMode = "authenticated"
    | .server.exposure = "private"
    | .server.bind = "loopback"
    | .server.host = "127.0.0.1"
    | .server.port = $port
    | .server.allowedHostnames = ((.server.allowedHostnames // []) + [$host, $short] | unique)
    | if $keepTelemetry == 1 then . else .telemetry.enabled = false end
  ' "$CONFIG" > "$tmp"
  if cmp -s "$tmp" "$CONFIG"; then
    rm -f "$tmp" "$backup"
    log "config already reconciled"
  else
    mv "$tmp" "$CONFIG"
    log "config updated (previous version: $backup)"
  fi
fi

# 3. Tailscale Serve: tailnet-only HTTPS with a real cert. Never Funnel.
BOARD_URL="https://${FQDN}:${PAPERCLIP_PORT}"
log "publishing $BOARD_URL -> http://127.0.0.1:$PAPERCLIP_PORT on the tailnet"
serve_https "$PAPERCLIP_PORT" "$PAPERCLIP_PORT"

# 4. Service: install if missing, then restart to pick up config.
if ! paperclipai service status >/dev/null 2>&1; then
  run paperclipai service install
fi
run paperclipai service restart --wait

# 5. Verify from the tailnet side, not just loopback.
if [[ "$DRY_RUN" != "1" ]]; then
  log "checking health through Tailscale Serve"
  health="$(mktemp)"
  for _ in $(seq 1 30); do
    if curl -fsS "$BOARD_URL/api/health" -o "$health" 2>/dev/null; then break; fi
    sleep 2
  done
  jq -e '.status == "ok" and .deploymentMode == "authenticated"' "$health" >/dev/null \
    || die "$BOARD_URL/api/health did not report ok/authenticated; see: paperclipai service logs"
  jq '{status, version, deploymentMode, deploymentExposure, bootstrapStatus}' "$health"
  assert_requires_auth "$BOARD_URL/api/companies"
  if jq -e '.bootstrapStatus == "bootstrap_pending"' "$health" >/dev/null; then
    warn "no instance admin yet. From a trusted device on the tailnet, open $BOARD_URL and choose 'Claim this instance',"
    warn "or run: paperclipai auth bootstrap-ceo   (prints a one-time admin invite URL)"
    warn "then lock sign-up: scripts/control-plane/lock-signup.sh"
  fi
  rm -f "$health"
fi

if [[ "$(uname -s)" == "Darwin" ]]; then
  if fdesetup isactive >/dev/null 2>&1; then
    warn "FileVault is on: after a cold boot this Mac waits at the unlock screen and the control plane stays down."
    warn "For planned restarts use: sudo fdesetup authrestart   (unlocks once, then boots straight into the session)."
  else
    warn "LaunchAgents only run inside a user session; keep automatic login on for this Mac."
  fi
fi
log "done. Board URL: $BOARD_URL"
