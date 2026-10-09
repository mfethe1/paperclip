#!/usr/bin/env bash
# Stop only the exact process recorded by this checkout's start script.
set -euo pipefail
: "${PAPERCLIP_REPO_DIR:?set PAPERCLIP_REPO_DIR to your local paperclip checkout}"
PID_FILE="${PAPERCLIP_PID_FILE:-$PAPERCLIP_REPO_DIR/.paperclip_server.pid}"
[[ -e "$PID_FILE" ]] || exit 0
pid=""
expected_start=""
IFS=$'\t' read -r pid expected_start < "$PID_FILE" || true
if [[ ! "$pid" =~ ^[0-9]+$ || -z "$expected_start" ]]; then
  echo "invalid Paperclip PID record; refusing to signal anything" >&2
  exit 1
fi
actual_start=$(LC_ALL=C ps -o lstart= -p "$pid" 2>/dev/null || true)
actual_start="${actual_start#"${actual_start%%[![:space:]]*}"}"
actual_start="${actual_start%"${actual_start##*[![:space:]]}"}"
expected_start="${expected_start#"${expected_start%%[![:space:]]*}"}"
expected_start="${expected_start%"${expected_start##*[![:space:]]}"}"
if [[ -n "$actual_start" && "$actual_start" == "$expected_start" ]]; then
  # PID/start-time binding prevents stale records from killing a reused PID.
  kill -TERM "$pid"
fi
rm -f "$PID_FILE"
