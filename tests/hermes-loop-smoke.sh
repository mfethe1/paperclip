#!/usr/bin/env bash
# End to end: a Hermes agent joins the board with scripts/node/join-hermes.sh, gets
# woken for an issue, and closes it with the paperclip-fleet skill's helper. Uses
# tests/fake_hermes.py in place of Hermes and a throwaway HOME and HERMES_HOME.
# Needs a local_trusted board (CI's throwaway instance, or a test instance).
#
# Usage: PAPERCLIP_API_URL=http://127.0.0.1:3100 tests/hermes-loop-smoke.sh [company-id]
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
B="${PAPERCLIP_API_URL:-http://127.0.0.1:3100}"; B="${B%/}"
CO="${1:-$(curl -fsS "$B/api/companies" | jq -r '.[0].id')}"
PORT="${FAKE_HERMES_PORT:-18643}"
T="$(mktemp -d)"
PID=""
cleanup() { if [[ -n "$PID" ]]; then kill "$PID" 2>/dev/null || true; fi; rm -rf "$T"; }
trap cleanup EXIT
fail() { echo "FAIL: $*" >&2; [[ -f "$T/hermes/last-input.txt" ]] && sed 's/^/  prompt| /' "$T/hermes/last-input.txt" | head -40 >&2; exit 1; }

export HOME="$T/home" HERMES_HOME="$T/hermes"
mkdir -p "$HOME" "$HERMES_HOME"
KEY="$(python3 -c 'import secrets; print(secrets.token_hex(24))')"
(umask 077 && printf 'API_SERVER_ENABLED=true\nAPI_SERVER_KEY=%s\n' "$KEY" > "$HERMES_HOME/.env")
FAKE_HERMES_KEY="$KEY" python3 "$ROOT/tests/fake_hermes.py" --port "$PORT" & PID=$!
for _ in $(seq 1 20); do curl -fsS "http://127.0.0.1:$PORT/health" >/dev/null 2>&1 && break; sleep 0.5; done

token="$(curl -fsS -X POST -H 'content-type: application/json' -d '{"allowedJoinTypes":"agent"}' \
  "$B/api/companies/$CO/invites" | jq -r .token)"
"$ROOT/scripts/node/join-hermes.sh" request --paperclip "$B" --invite "$token" \
  --name "Hermes (smoke)" --api-base-url "http://127.0.0.1:$PORT"
req="$(basename "$(ls "$HOME"/.config/paperclip-fleet/join-*.json)" .json)"; req="${req#join-}"
curl -fsS -X POST -H 'content-type: application/json' -d '{}' \
  "$B/api/companies/$CO/join-requests/$req/approve" >/dev/null
"$ROOT/scripts/node/join-hermes.sh" claim --paperclip "$B" --request "$req"

grep -q '^PAPERCLIP_API_KEY=.' "$HERMES_HOME/.env" || fail "claim did not write PAPERCLIP_API_KEY"
[[ -f "$HERMES_HOME/skills/paperclip/SKILL.md" ]] || fail "board's paperclip skill not installed"
[[ -x "$HERMES_HOME/skills/paperclip-fleet/scripts/paperclip-issue-update.sh" ]] || fail "paperclip-fleet skill not installed"
[[ "$(stat -c %a "$HERMES_HOME/.env" 2>/dev/null || stat -f %Lp "$HERMES_HOME/.env")" == "600" ]] || fail ".env is not 0600"
agent="$(sed -n 's/^PAPERCLIP_AGENT_ID=//p' "$HERMES_HOME/.env")"

issue="$(curl -fsS -X POST -H 'content-type: application/json' \
  -d "{\"title\":\"Hermes loop smoke\",\"status\":\"todo\",\"assigneeAgentId\":\"$agent\"}" \
  "$B/api/companies/$CO/issues" | jq -r .identifier)"
echo "woke Hermes with $issue"
status=""
for _ in $(seq 1 60); do
  status="$(curl -fsS "$B/api/issues/$issue" | jq -r .status)"
  [[ "$status" == "done" ]] && break
  sleep 2
done
[[ "$status" == "done" ]] || fail "$issue is '$status', not done"
curl -fsS "$B/api/issues/$issue/comments" | jq -e 'any(.[]; .body | test("fake Hermes closed this"))' >/dev/null \
  || fail "no handoff comment on $issue"
run="$(curl -fsS "$B/api/companies/$CO/heartbeat-runs?agentId=$agent&limit=5" | jq -r '.[0].status')"
echo "ok: $issue closed by the Hermes agent through its own run (run status: $run)"
