# shellcheck shell=bash
# Shared helpers for fleet scripts. Source, don't execute.

set -euo pipefail

# Pinned Paperclip release. Bump deliberately (docs/RUNBOOK.md, "Upgrade Paperclip"), never float.
PAPERCLIP_VERSION="${PAPERCLIP_VERSION:-2026.1005.0}"
PAPERCLIP_PORT="${PAPERCLIP_PORT:-3100}"
HERMES_GATEWAY_PORT="${HERMES_GATEWAY_PORT:-8642}"
OPENCLAW_GATEWAY_PORT="${OPENCLAW_GATEWAY_PORT:-18789}"

# shellcheck disable=SC2034  # used by the scripts that source this file
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

log()  { printf '\033[1;34m==>\033[0m %s\n' "$*" >&2; }
warn() { printf '\033[1;33mwarn:\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }

need() {
  command -v "$1" >/dev/null 2>&1 || die "missing required command: $1${2:+ ($2)}"
}

# DRY_RUN=1 prints mutating commands instead of running them.
run() {
  if [[ "${DRY_RUN:-0}" == "1" ]]; then
    printf '[dry-run] %q' "$1" >&2; shift
    printf ' %q' "$@" >&2; printf '\n' >&2
  else
    "$@"
  fi
}

# The macOS GUI build of Tailscale does not put the CLI on PATH.
tailscale_bin() {
  if command -v tailscale >/dev/null 2>&1; then
    command -v tailscale
  elif [[ -x /Applications/Tailscale.app/Contents/MacOS/Tailscale ]]; then
    echo /Applications/Tailscale.app/Contents/MacOS/Tailscale
  else
    die "tailscale CLI not found; install Tailscale and log in to the tailnet"
  fi
}

# This node's MagicDNS name without the trailing dot, e.g. mack.tailabc123.ts.net
tailnet_fqdn() {
  local ts
  ts="$(tailscale_bin)"
  "$ts" status --json | jq -r '.Self.DNSName' | sed 's/\.$//'
}

# MagicDNS suffix for the tailnet, e.g. tailabc123.ts.net
tailnet_suffix() {
  local ts
  ts="$(tailscale_bin)"
  "$ts" status --json | jq -r '.MagicDNSSuffix'
}

# Publish https://<this-node>:<port> -> http://127.0.0.1:<target_port> on the tailnet.
# Same-number ports keep URLs predictable and avoid :443, which peer-relay owns on
# several hosts. Refuses to replace a mapping that points somewhere else.
serve_https() {
  local port="$1" target_port="$2" ts fqdn current
  ts="$(tailscale_bin)"
  fqdn="$(tailnet_fqdn)"
  current="$("$ts" serve status --json 2>/dev/null \
    | jq -r --arg k "${fqdn}:${port}" '.Web[$k].Handlers["/"].Proxy // empty' 2>/dev/null || true)"
  if [[ -n "$current" && "$current" != "http://127.0.0.1:${target_port}" ]]; then
    die "tailscale serve :${port} already proxies to ${current}; pick another port (it may be peer-relay or Buzz)"
  fi
  if [[ "$current" == "http://127.0.0.1:${target_port}" ]]; then
    log "tailscale serve :${port} already -> 127.0.0.1:${target_port}"
    return 0
  fi
  run "$ts" serve --bg --https="${port}" "http://127.0.0.1:${target_port}"
}

# Fleet rule: nothing on the tailnet answers 200 without credentials.
assert_requires_auth() {
  local url="$1" code
  code="$(curl -sS -o /dev/null -w '%{http_code}' "$url" || echo 000)"
  if [[ "$code" == "200" ]]; then
    die "$url answered 200 without credentials; do not join it until auth is on"
  fi
  log "$url without credentials -> HTTP $code (ok, not 200)"
}

require_node24() {
  need node "Paperclip requires Node.js >= 24.11"
  local v
  v="$(node -p 'process.versions.node')"
  node -e '
    const [a,b]=process.versions.node.split(".").map(Number);
    process.exit(a>24||(a===24&&b>=11)?0:1)' \
    || die "Node.js $v is too old; Paperclip ${PAPERCLIP_VERSION} requires >= 24.11"
}

# Paperclip CLI pinned to the fleet version, regardless of what's on PATH.
pc() {
  if command -v paperclipai >/dev/null 2>&1 \
     && [[ "$(paperclipai --version 2>/dev/null)" == "$PAPERCLIP_VERSION" ]]; then
    paperclipai "$@"
  else
    npx -y "paperclipai@${PAPERCLIP_VERSION}" "$@"
  fi
}

paperclip_config_path() {
  echo "${PAPERCLIP_HOME:-$HOME/.paperclip}/instances/${PAPERCLIP_INSTANCE_ID:-default}/config.json"
}
