#!/usr/bin/env bash
# Install or reconcile the fleet's Paperclip control plane on the board host (Rosie;
# check a candidate first with scripts/control-plane/preflight.sh).
#
# Result:
#   - paperclipai ${PAPERCLIP_VERSION} in the managed CLI store (~/.paperclip/cli)
#   - instance in authenticated/private mode, listening on 127.0.0.1:3100 only
#   - Tailscale Serve: https://<this-node>.<tailnet>.ts.net:3100 -> http://127.0.0.1:3100
#     (other Serve ports, e.g. :443 for OpenClaw or peer-relay, are left alone)
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
if [[ "$(uname -s)" == "Darwin" ]]; then
  # The LaunchAgent lives in the user's GUI session; over plain SSH there is none.
  launchctl print "gui/$(id -u)" >/dev/null 2>&1 \
    || die "no GUI login session for $(id -un); log in at the console or via Screen Sharing, then re-run"
fi

# 1. Managed, pinned CLI install (atomic switch, keeps two rollbacks).
export PATH="$HOME/.local/bin:$PATH"   # managed shim location
if [[ "$(paperclip_cli_version)" != "$PAPERCLIP_VERSION" ]]; then
  log "installing paperclipai ${PAPERCLIP_VERSION} into the managed CLI store"
  # Runs under the Node 24 that ensure_node24 put first on PATH; the managed shim
  # (~/.local/bin/paperclipai) pins that Node for the CLI and the LaunchAgent.
  run npx -y "paperclipai@${PAPERCLIP_VERSION}" install --version "$PAPERCLIP_VERSION"
  export PATH="$HOME/.local/bin:$PATH"
fi
# Every run: install/update rewrite the launcher, so re-pin it (stable node path +
# a PATH where agents find claude/codex/gh). No-op off macOS.
run repin_managed_shim
[[ "$DRY_RUN" == "1" ]] || [[ "$(paperclip_cli_version)" == "$PAPERCLIP_VERSION" ]] \
  || die "paperclipai on PATH ($(command -v paperclipai || echo none)) reports '$(paperclip_cli_version)', expected $PAPERCLIP_VERSION"

# 2. Instance config: create on first run, otherwise reconcile.
CONFIG="$(paperclip_config_path)"
if [[ "$DRY_RUN" != "1" ]]; then
  trap 'warn "install interrupted; re-run scripts/control-plane/install.sh to finish (it is idempotent)"' EXIT
fi
if [[ ! -f "$CONFIG" ]]; then
  log "no instance at $CONFIG; onboarding (authenticated/private) and installing the service"
  log "expected: onboard may warn that the dashboard is not ready (up to ~60s); the next steps fix the listener"
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

# 4. Service: `service install` is idempotent (rewrites the LaunchAgent only if it
# changed); `service status` exits 0 even when nothing is installed, so don't gate on it.
run paperclipai service install
run paperclipai service restart --wait --expected-version "$PAPERCLIP_VERSION"

# 5. Verify. Loopback is authoritative (a host often can't reach its own tailnet URL:
# hairpin); the tailnet URL is checked once and only warns. fleet-check.sh from
# another node is the real end-to-end test.
if [[ "$DRY_RUN" != "1" ]]; then
  LOCAL_URL="http://127.0.0.1:${PAPERCLIP_PORT}"
  health="$(curl -fsS -m 10 "$LOCAL_URL/api/health" 2>/dev/null || true)"
  jq -e '.status == "ok" and .deploymentMode == "authenticated"' >/dev/null 2>&1 <<<"$health" \
    || die "$LOCAL_URL/api/health did not report ok/authenticated; see: paperclipai service logs"
  jq '{status, deploymentMode, deploymentExposure, bootstrapStatus}' <<<"$health"
  assert_requires_auth "$LOCAL_URL/api/companies"
  if ! curl -fsS -m 10 "$BOARD_URL/api/health" >/dev/null 2>&1; then
    warn "$BOARD_URL not reachable from this host (often hairpin NAT); verify from another node: scripts/fleet-check.sh"
    "$TS" serve status 2>/dev/null || true
  fi
  if jq -e '.bootstrapStatus == "bootstrap_pending"' >/dev/null 2>&1 <<<"$health"; then
    warn "no instance admin yet. From a trusted device on the tailnet, open $BOARD_URL and choose 'Claim this instance',"
    warn "or run: paperclipai auth bootstrap-ceo   (prints a one-time admin invite URL)"
    warn "then lock sign-up: scripts/control-plane/lock-signup.sh"
  fi
  trap - EXIT
  if command -v zsh >/dev/null 2>&1 && ! zsh -lic 'command -v paperclipai' >/dev/null 2>&1; then
    warn "paperclipai is not on your login shell's PATH; add to ~/.zshrc: export PATH=\"\$HOME/.local/bin:\$PATH\""
  fi
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
