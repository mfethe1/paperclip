#!/usr/bin/env bash
# Read-only check: is this machine a good always-on host for the Paperclip board?
# Changes nothing. Prints a table and a verdict; paste it into the conversation or an issue.
#
# Usage: scripts/control-plane/preflight.sh
set -uo pipefail
# shellcheck source=../lib/common.sh
source "$(dirname "$0")/../lib/common.sh"
set +e   # a failed probe is a finding, not a reason to stop

rows=()
fails=0; warns=0
row() { # check result detail
  rows+=("| $1 | $2 | $3 |")
  case "$2" in FAIL) fails=$((fails + 1)) ;; warn) warns=$((warns + 1)) ;; esac
}
has() { command -v "$1" >/dev/null 2>&1; }
mac() { [[ "$(uname -s)" == "Darwin" ]]; }

row "host" ok "$(hostname -s 2>/dev/null || hostname) · $(uname -s) $(uname -m) · up $(uptime | sed -E 's/.*up ([^,]+),.*/\1/')"

# Node: default and side-by-side 24+
default_node="$(node -v 2>/dev/null || echo none)"
if node24="$(find_node24)"; then
  row "node >= 24.11" ok "$("$node24" -v) at $node24 (default node: $default_node, left alone)"
else
  row "node >= 24.11" warn "none found (default node: $default_node). install.sh --install-node will run: brew install node@24"
  has brew || row "homebrew" FAIL "not installed; needed for --install-node (or install Node 24 another way)"
fi
for c in jq curl; do
  if has "$c"; then row "$c" ok "$(command -v "$c")"; else row "$c" FAIL "missing"; fi
done

# Tailscale
if TS="$(tailscale_bin 2>/dev/null)"; then
  st="$("$TS" status --json 2>/dev/null)"
  if [[ -n "$st" ]] && jq -e '.BackendState == "Running"' >/dev/null 2>&1 <<<"$st"; then
    row "tailscale" ok "running as $(jq -r '.Self.DNSName' <<<"$st" | sed 's/\.$//' | cut -d. -f1) (full name withheld)"
    if jq -e '(.CertDomains // []) | length > 0' >/dev/null 2>&1 <<<"$st"; then
      row "tailnet HTTPS certs" ok "enabled"
    else
      row "tailnet HTTPS certs" FAIL "not enabled: admin console > DNS > enable MagicDNS and HTTPS certificates"
    fi
    used="$("$TS" serve status --json 2>/dev/null | jq -r '(.TCP // {}) | keys | join(", ")' 2>/dev/null)"
    row "tailscale serve ports in use" ok "${used:-none}"
    if [[ ",${used// /}," == *",${PAPERCLIP_PORT},"* ]]; then
      row "serve port ${PAPERCLIP_PORT} free" FAIL "already published by something else; pick another PAPERCLIP_PORT"
    else
      row "serve port ${PAPERCLIP_PORT} free" ok "free"
    fi
  else
    row "tailscale" FAIL "installed but not running/logged in"
  fi
else
  row "tailscale" FAIL "CLI not found"
fi

# Local port
if has lsof && lsof -nP -iTCP:"$PAPERCLIP_PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  row "local port ${PAPERCLIP_PORT}" warn "something already listens: $(lsof -nP -iTCP:"$PAPERCLIP_PORT" -sTCP:LISTEN | awk 'NR==2{print $1}')"
else
  row "local port ${PAPERCLIP_PORT}" ok "free"
fi

# Disk (home volume)
free_gb="$(df -Pk "$HOME" | awk 'NR==2 {printf "%d", $4/1024/1024}')"
if (( free_gb < 20 )); then row "free disk (home)" FAIL "${free_gb} GB; the board's database, backups and agent workspaces need room"
elif (( free_gb < 60 )); then row "free disk (home)" warn "${free_gb} GB; fine to start, watch it"
else row "free disk (home)" ok "${free_gb} GB"; fi

# Survives reboots and stays awake (macOS)
if mac; then
  fv="$(fdesetup status 2>/dev/null | head -1)"
  auto="$(defaults read /Library/Preferences/com.apple.loginwindow autoLoginUser 2>/dev/null)"
  if [[ "$fv" == *"On"* ]]; then
    row "FileVault" warn "on: after an unplanned reboot the board stays down until someone unlocks this Mac (planned reboots: sudo fdesetup authrestart)"
  else
    row "FileVault" ok "${fv:-unknown}"
  fi
  if [[ -n "$auto" ]]; then row "automatic login" ok "user ${auto}"
  elif [[ "$fv" == *"On"* ]]; then row "automatic login" warn "off (not possible with FileVault on)"
  else row "automatic login" warn "off: the LaunchAgent only starts after someone logs in"; fi
  sleep_min="$(pmset -g 2>/dev/null | awk '$1=="sleep" {print $2; exit}')"
  if [[ "$sleep_min" == "0" ]]; then row "system sleep" ok "never"
  else row "system sleep" FAIL "sleeps after ${sleep_min:-?} min: sudo pmset -a sleep 0 (display sleep is fine)"; fi
  restart="$(pmset -g 2>/dev/null | awk '$1=="autorestart" {print $2; exit}')"
  if [[ "$restart" == "1" ]]; then row "restart after power loss" ok "on"
  else row "restart after power loss" warn "off: sudo pmset -a autorestart 1"; fi
fi

# Existing Paperclip
cfg="$(paperclip_config_path)"
if [[ -f "$cfg" ]]; then
  row "existing Paperclip instance" warn "found at ${cfg/#$HOME/\~} (install.sh reconciles it in place, data untouched)"
else
  row "existing Paperclip instance" ok "none"
fi

# Agent runtimes the board would run locally
if has claude; then row "Claude Code" ok "$(claude --version 2>/dev/null | head -1); make sure it is logged in on THIS machine (logins are never copied between hosts)"
else row "Claude Code" warn "not installed: the Chief of Staff, Builder and Fleet Ops agents use it"; fi
if has codex; then
  if [[ -f "$HOME/.codex/auth.json" ]]; then row "Codex" ok "$(codex --version 2>/dev/null | head -1), logged in"
  else row "Codex" warn "$(codex --version 2>/dev/null | head -1), no login found: run codex login"; fi
else row "Codex" warn "not installed: the Verifier agent uses it"; fi

# OpenClaw on this host
code="$(curl -s -o /dev/null -m 3 -w '%{http_code}' "http://127.0.0.1:${OPENCLAW_GATEWAY_PORT}/" 2>/dev/null || echo 000)"
if [[ "$code" != "000" ]]; then row "OpenClaw gateway" ok "listening on 127.0.0.1:${OPENCLAW_GATEWAY_PORT}"
else row "OpenClaw gateway" ok "not on this host"; fi

echo "| Check | Result | Detail |"
echo "|---|---|---|"
printf '%s\n' "${rows[@]}"
echo
if (( fails > 0 )); then
  echo "Verdict: NOT READY. Fix the ${fails} FAIL row(s) first; ${warns} warning(s)."
  exit 1
fi
echo "Verdict: ready to host the board (${warns} warning(s) to review)."
