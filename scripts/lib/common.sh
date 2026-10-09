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

# Paperclip needs Node >= 24.11. Hosts like Mack keep an older default `node` for
# other services (Hermes, Buzz, OpenClaw), so never replace it: find a side-by-side
# Node 24+ and put it first on PATH for this script only. `paperclipai install`
# pins whichever Node runs it into its launcher shim, so the background service
# keeps using Node 24 regardless of the system default.
node_ok() {
  "$1" -e 'const [a,b]=process.versions.node.split(".").map(Number);process.exit(a>24||(a===24&&b>=11)?0:1)' 2>/dev/null
}

find_node24() {
  local c prefix restore
  local candidates=()
  if [[ -n "${PAPERCLIP_NODE:-}" ]]; then candidates+=("$PAPERCLIP_NODE"); fi
  if command -v node >/dev/null 2>&1; then candidates+=("$(command -v node)"); fi
  if command -v brew >/dev/null 2>&1; then
    prefix="$(brew --prefix 2>/dev/null || true)"
    if [[ -n "$prefix" ]]; then candidates+=("$prefix/opt/node@24/bin/node" "$prefix/opt/node/bin/node"); fi
  fi
  candidates+=(/opt/homebrew/opt/node@24/bin/node /usr/local/opt/node@24/bin/node)
  # Version managers (nvm, fnm, volta, asdf, mise). nullglob keeps unmatched patterns out.
  restore="$(shopt -p nullglob || true)"
  shopt -s nullglob
  for c in "$HOME"/.nvm/versions/node/v2[4-9].*/bin/node \
           "$HOME"/.local/share/fnm/node-versions/v2[4-9].*/installation/bin/node \
           "$HOME/Library/Application Support/fnm/node-versions"/v2[4-9].*/installation/bin/node \
           "$HOME"/.volta/tools/image/node/2[4-9].*/bin/node \
           "$HOME"/.asdf/installs/nodejs/2[4-9].*/bin/node \
           "$HOME"/.local/share/mise/installs/node/2[4-9]*/bin/node; do
    candidates+=("$c")
  done
  eval "$restore"
  for c in "${candidates[@]}"; do
    if [[ -x "$c" ]] && node_ok "$c"; then
      printf '%s\n' "$c"
      return 0
    fi
  done
  return 1
}

# Usage: INSTALL_NODE=1 ensure_node24   (INSTALL_NODE=1 allows `brew install node@24`)
ensure_node24() {
  local node24 bindir current
  current="$(node -v 2>/dev/null || echo none)"
  if ! node24="$(find_node24)"; then
    if [[ "${INSTALL_NODE:-0}" != "1" ]]; then
      die "Paperclip ${PAPERCLIP_VERSION} needs Node.js >= 24.11; the default node here is ${current}.
  Install Node 24 side by side (keg-only; does NOT change your default node):
      brew install node@24
  then re-run this script, or re-run it with --install-node to do that for you."
    fi
    need brew "Homebrew is required for --install-node (https://brew.sh)"
    log "installing Homebrew node@24 (keg-only: the default node stays ${current})"
    run brew install node@24
    if [[ "${DRY_RUN:-0}" == "1" ]]; then
      log "[dry-run] would continue with Homebrew node@24"
      return 0
    fi
    node24="$(find_node24)" || die "brew installed node@24 but it was not found; check: brew --prefix node@24"
  fi
  bindir="$(dirname "$node24")"
  export PATH="$bindir:$PATH"
  log "using Node $("$node24" -v) from $bindir for Paperclip (default node unchanged: ${current})"
}

# Version of the paperclipai on PATH, or empty. A managed install prints extra
# detail after the number ("2026.1005.0 (managed npm pinned; payload ...)").
paperclip_cli_version() {
  command -v paperclipai >/dev/null 2>&1 || return 0
  paperclipai --version 2>/dev/null | awk 'NR==1 {print $1}' || true
}

# Paperclip CLI pinned to the fleet version, regardless of what's on PATH.
pc() {
  if [[ "$(paperclip_cli_version)" == "$PAPERCLIP_VERSION" ]]; then
    paperclipai "$@"
  else
    ensure_node24
    npx -y "paperclipai@${PAPERCLIP_VERSION}" "$@"
  fi
}

paperclip_config_path() {
  echo "${PAPERCLIP_HOME:-$HOME/.paperclip}/instances/${PAPERCLIP_INSTANCE_ID:-default}/config.json"
}
