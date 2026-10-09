#!/usr/bin/env bash
# Start a local Paperclip dev server (sanitized publication version).
#
# Changes from the operator's original:
#   - No default JWT/auth secret: PAPERCLIP_AGENT_JWT_SECRET is REQUIRED and the
#     script fails loudly when unset (a missing secret must never silently
#     fall back to a shared placeholder).
#   - No hardcoded account paths: PAPERCLIP_REPO_DIR is REQUIRED and must point
#     at a local checkout of the Paperclip repository.
set -euo pipefail

: "${PAPERCLIP_REPO_DIR:?set PAPERCLIP_REPO_DIR to your local paperclip checkout}"
: "${PAPERCLIP_AGENT_JWT_SECRET:?set PAPERCLIP_AGENT_JWT_SECRET; no default is provided}"

export PAPERCLIP_DEPLOYMENT_MODE="${PAPERCLIP_DEPLOYMENT_MODE:-authenticated}"
export PAPERCLIP_DEPLOYMENT_EXPOSURE="${PAPERCLIP_DEPLOYMENT_EXPOSURE:-private}"
export BETTER_AUTH_SECRET="${BETTER_AUTH_SECRET:-$PAPERCLIP_AGENT_JWT_SECRET}"

# Loopback by default; set HOST=0.0.0.0 only inside a trusted network.
export HOST="${HOST:-127.0.0.1}"
export PORT="${PAPERCLIP_PORT:-3100}"

LOG_FILE="${PAPERCLIP_LOG:-$PAPERCLIP_REPO_DIR/paperclip_server.log}"
PID_FILE="${PAPERCLIP_PID_FILE:-$PAPERCLIP_REPO_DIR/.paperclip_server.pid}"

mkdir -p "$(dirname "$LOG_FILE")"
cd "$PAPERCLIP_REPO_DIR"

# Never search/kill by command-line substring: that can terminate unrelated
# Paperclip servers. Only stop a process recorded by this checkout's PID file.
if [[ -e "$PID_FILE" ]]; then
  "$PWD/contrib/fleet-184991/scripts/paperclip-dev-stop.sh"
fi
nohup pnpm --filter @paperclipai/server run dev >> "$LOG_FILE" 2>&1 &
pid=$!
# Store PID plus kernel process start identity to reject PID reuse on stop.
# LC_ALL=C plus full whitespace trimming matches paperclip-dev-stop.sh exactly.
start=$(LC_ALL=C ps -o lstart= -p "$pid" || true)
start="${start#"${start%%[![:space:]]*}"}"
start="${start%"${start##*[![:space:]]}"}"
if [[ -z "$start" ]]; then kill "$pid" 2>/dev/null || true; exit 1; fi
printf '%s\t%s\n' "$pid" "$start" > "$PID_FILE"

echo "Paperclip server starting as PID $pid on http://$HOST:$PORT"
echo "Logs: $LOG_FILE"
