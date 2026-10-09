#!/usr/bin/env bash
# Read-only diagnosis of agent errors on the Paperclip board.
#
# Collects health, agents, recent heartbeat runs, failed-run details and issue
# recovery actions over the API, groups failures by cause using
# tools/agent-errors.tsv (signals verified against Paperclip 2026.1005.0), and
# prints a markdown report with the fix for each group. Hostnames, IPs, home
# paths, UUIDs and tokens are redacted, so the report can go into an issue.
#
# Only HTTP GET is ever sent. It never wakes, retries, or changes anything.
#
# Usage: scripts/diagnose.sh [--board-url URL] [--company-id ID] [--limit 200]
#                            [--detail-max 20] [--server-log FILE] [--out FILE] [--strict]
# Env:   PAPERCLIP_API_URL, PAPERCLIP_API_KEY (a board key, or an agent key in agent runs),
#        PAPERCLIP_COMPANY_ID
# Exit:  0, or 1 with --strict when any FAIL/CRITICAL is reported.
set -euo pipefail
# shellcheck source=lib/common.sh
source "$(dirname "$0")/lib/common.sh"

BASE="${PAPERCLIP_API_URL:-http://127.0.0.1:${PAPERCLIP_PORT}}"
CO="${PAPERCLIP_COMPANY_ID:-}"
LIMIT=200; DETAIL_MAX=20; SERVER_LOG=""; OUT=""; STRICT=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --board-url) BASE="$2"; shift 2 ;;
    --company-id) CO="$2"; shift 2 ;;
    --limit) LIMIT="$2"; shift 2 ;;
    --detail-max) DETAIL_MAX="$2"; shift 2 ;;
    --server-log) SERVER_LOG="$2"; shift 2 ;;
    --out) OUT="$2"; shift 2 ;;
    --strict) STRICT=1; shift ;;
    -h|--help) sed -n '2,17p' "$0"; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
done
BASE="${BASE%/}"
need curl
need jq
CATALOG="$REPO_ROOT/tools/agent-errors.tsv"
[[ -f "$CATALOG" ]] || die "missing $CATALOG"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
AUTH=()
if [[ -n "${PAPERCLIP_API_KEY:-}" ]]; then  # header file, not argv: ps can't show the key
  printf 'authorization: Bearer %s\n' "$PAPERCLIP_API_KEY" > "$WORK/auth.hdr"
  AUTH=(-H "@$WORK/auth.hdr")
fi
CALLS="$WORK/calls.txt"; : > "$CALLS"

# The only way this script talks to the board.
api_get() { # path outfile -> returns 0 on HTTP 200
  local path="$1" out="$2" code
  case "$path" in *provider-trace*) die "refusing to read $path" ;; esac
  code="$(curl -s -m 30 -o "$out" -w '%{http_code}' ${AUTH[@]+"${AUTH[@]}"} "$BASE$path" 2>/dev/null || true)"
  code="${code:-000}"
  printf '%s GET %s\n' "$code" "${path%%\?*}" >> "$CALLS"
  if [[ "$code" == "403" && "$path" == *heartbeat-runs* ]]; then
    warn "403 on $path: this key may not read run telemetry (low-trust agent or another company); use a board key"
  fi
  [[ "$code" == "200" ]]
}

# --- collect ---------------------------------------------------------------
api_get /api/health "$WORK/health.json" || die "no health response from $BASE (HTTP $(tail -1 "$CALLS" | cut -d' ' -f1))"
if [[ -z "$CO" ]]; then
  api_get /api/companies "$WORK/companies.json" || die "cannot list companies; pass --company-id or a board PAPERCLIP_API_KEY"
  n="$(jq 'length' "$WORK/companies.json")"
  [[ "$n" == "1" ]] || die "board has $n companies; pass --company-id (one of: $(jq -r '[.[].name] | join(", ")' "$WORK/companies.json"))"
  CO="$(jq -r '.[0].id' "$WORK/companies.json")"
fi
api_get "/api/companies/$CO/agents" "$WORK/agents.json" || echo '[]' > "$WORK/agents.json"
api_get "/api/companies/$CO/heartbeat-runs?summary=true&limit=$LIMIT" "$WORK/runs.json" || echo '[]' > "$WORK/runs.json"
api_get "/api/companies/$CO/issues?limit=1000" "$WORK/issues.json" || echo '[]' > "$WORK/issues.json"

# Full detail for the newest failed runs (structured reasons live only there).
mkdir -p "$WORK/runs"
jq -r '[.[] | select(.status == "failed" or .status == "timed_out")]
       | sort_by(.createdAt) | reverse | .[].id' "$WORK/runs.json" | head -n "$DETAIL_MAX" > "$WORK/detail-ids.txt"
while IFS= read -r id; do
  [[ -n "$id" ]] || continue
  if api_get "/api/heartbeat-runs/$id" "$WORK/runs/$id.json"; then
    if [[ "$(jq -r '.errorCode // ""' "$WORK/runs/$id.json")" == "workspace_validation_failed" ]] \
       && api_get "/api/heartbeat-runs/$id/log" "$WORK/runs/$id.log"; then
      grep -o 'fatal:[^"\\]*' "$WORK/runs/$id.log" | tail -1 > "$WORK/runs/$id.fatal" || true
    fi
  fi
done < "$WORK/detail-ids.txt"

# Recovery actions for stuck issues (blocked, or in progress with a failed latest run).
mkdir -p "$WORK/recovery"
jq -r '.[] | select(.status == "blocked" or .status == "in_progress") | .id' "$WORK/issues.json" | head -n 25 \
| while IFS= read -r iid; do
    api_get "/api/issues/$iid/recovery-actions" "$WORK/recovery/$iid.json" || rm -f "$WORK/recovery/$iid.json"
  done

if jq -e 'any(.[]; .adapterType == "codex_local")' "$WORK/agents.json" >/dev/null; then
  api_get "/api/companies/$CO/adapters/codex_local/auth-signal" "$WORK/codex-auth.json" || true
fi

# --- classify --------------------------------------------------------------
jq -R -s 'split("\n") | map(select(length > 0) | split("\t")) | .[1:]
          | map({id: .[0], adapter: .[1], code: .[2], reason: .[3], msg: .[4], title: .[5], fix: .[6]})' \
   "$CATALOG" > "$WORK/catalog.json"
# Merge summary rows with whatever detail we fetched.
jq -s '.' "$WORK"/runs/*.json 2>/dev/null > "$WORK/details.json" || echo '[]' > "$WORK/details.json"
[[ -s "$WORK/details.json" ]] || echo '[]' > "$WORK/details.json"

jq -n --slurpfile runs "$WORK/runs.json" --slurpfile det "$WORK/details.json" \
      --slurpfile agents "$WORK/agents.json" --slurpfile cat "$WORK/catalog.json" '
  ($agents[0] | map({key: .id, value: {name, adapterType}}) | from_entries) as $amap
  | ($det[0] | map({key: .id, value: .}) | from_entries) as $dmap
  | [ $runs[0][] | select(.status == "failed" or .status == "timed_out")
      | . as $r | ($dmap[$r.id] // $r) as $d
      | ($amap[$r.agentId] // {name: "unknown agent", adapterType: ""}) as $a
      | { run: $r.id, agent: $a.name, adapter: $a.adapterType, status: $r.status,
          createdAt: $r.createdAt,
          code: ($d.errorCode // $r.errorCode // ""),
          reason: ($d.resultJson.configurationIncomplete.reason // $d.resultJson.workspaceValidation.reason // ""),
          error: ($d.error // $r.error // ""),
          exhausted: ($d.retryExhaustedReason // "") }
      | . as $f
      | ([ $cat[0][] | . as $c
           | select($c.adapter == "*" or $c.adapter == $f.adapter)
           | select($c.code == "" or ($f.code | test($c.code)))
           | select($c.reason == "" or $c.reason == $f.reason)
           | select($c.msg == "" or ($f.error | test($c.msg))) ] | first) as $m
      | . + { cat: ($m.id // "unclassified"),
              title: ($m.title // ("Unclassified failure (" + (if $f.code == "" then $f.status else $f.code end) + ")")),
              fix: ($m.fix // "Not in the catalog yet: read the error and the run log, then add a row to tools/agent-errors.tsv.") } ]
  | group_by([.cat, .agent])
  | map({ cat: .[0].cat, title: .[0].title, fix: .[0].fix, agent: .[0].agent, adapter: .[0].adapter,
          count: length, latest: (map(.createdAt) | max),
          runs: (sort_by(.createdAt) | reverse | map(.run[0:8]) | .[0:5]),
          code: .[0].code, reason: .[0].reason,
          error: ((sort_by(.createdAt) | last | .error) | split("\n") | map(select(length > 0)) | join(" / ") | .[0:220]),
          exhausted: (map(select(.exhausted != "")) | length > 0) })
  | sort_by(.latest) | reverse' > "$WORK/groups.json"

# --- report ----------------------------------------------------------------
FAILS=0; CRIT=0
report() {
  local h="$WORK/health.json"
  echo "# Paperclip diagnosis"
  echo
  echo "Board: $BASE · company ${CO:0:8} · generated $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo
  echo "## Health"
  echo
  jq -r '"- status: \(.status) · mode: \(.deploymentMode // "?")/\(.deploymentExposure // "?") · version: \(.version // "hidden") · admin: \(if .bootstrapStatus == "bootstrap_pending" then "NOT CLAIMED" else (.bootstrapStatus // "?") end)"' "$h"
  local ver; ver="$(jq -r '.version // ""' "$h")"
  if [[ -n "$ver" && "$ver" != "$PAPERCLIP_VERSION" ]]; then
    echo "- WARN: board runs $ver; this repo's catalog and scripts target $PAPERCLIP_VERSION"
  fi
  # A missing backup is normal until the first hourly backup has run.
  jq -r '((.serverInfo.processStartedAt // null) as $s
          | if $s then ((now - ($s | sub("\\.[0-9]+Z$"; "Z") | fromdateiso8601)) / 60) else null end) as $up
         | .warnings[]?
         | "- \(if .code == "database_backup_missing" and $up != null and $up < 90
                then "INFO (server up \($up | floor) min; first backup runs after ~60 min)"
                else "WARN" end): \(.code): \(.message)"' "$h"
  echo
  local total failed retrying agents_err
  total="$(jq 'length' "$WORK/runs.json")"
  failed="$(jq '[.[] | select(.status == "failed" or .status == "timed_out")] | length' "$WORK/runs.json")"
  retrying="$(jq '[.[] | select(.status == "scheduled_retry")] | length' "$WORK/runs.json")"
  agents_err="$(jq '[.[] | select(.status == "error")] | length' "$WORK/agents.json")"
  echo "## Summary"
  echo
  echo "- agents: $(jq 'length' "$WORK/agents.json") ($agents_err in error, $(jq '[.[] | select(.status == "paused")] | length' "$WORK/agents.json") paused)"
  echo "- runs scanned: $total (newest $LIMIT) · failed: $failed · retrying now: $retrying · detail fetched for $(wc -l < "$WORK/detail-ids.txt" | tr -d ' ')"
  echo "- distinct problems: $(jq 'length' "$WORK/groups.json")"
  echo
  echo "## Problems"
  echo
  if [[ "$(jq 'length' "$WORK/groups.json")" == "0" ]]; then
    echo "No failed runs in the scanned window."
  else
    jq -r '.[] | "### FAIL: \(.title)\n\n- agent: \(.agent) (\(.adapter)) · \(.count) failed run(s), latest \(.latest)\(if .exhausted then " · automatic retries exhausted" else "" end)\n- signal: `\(.code)`\(if .reason != "" then " / `\(.reason)`" else "" end) · runs: \(.runs | join(", "))\n- last error: \(.error)\n- **Fix:** \(.fix)\n"' "$WORK/groups.json"
    for f in "$WORK"/runs/*.fatal; do
      [[ -s "$f" ]] && echo "- clone failure detail: $(cat "$f")"
    done
  fi
  echo
  echo "## Agents"
  echo
  echo "| Agent | Adapter | Status | Note |"
  echo "|---|---|---|---|"
  jq -r '.[] | "| \(.name) | \(.adapterType) | \(.status) | \(
      if .status == "error" then ((.errorReason // "") | split("\n") | map(select(length > 0)) | join(" / ") | .[0:120])
      elif .status == "paused" then "paused: resume with approval once its prerequisites pass"
      else "" end) |"' "$WORK/agents.json"
  echo
  # Gateway agents: transport only, never key values.
  local gw
  gw="$(jq -r '.[] | select(.adapterType == "hermes_gateway" or .adapterType == "openclaw_gateway")
      | (.adapterConfig.apiBaseUrl // .adapterConfig.url // "") as $u
      | ($u | capture("^(?<s>[a-z]+)://(?<h>[^/:]+)") // {s: "", h: ""}) as $p
      | ($p.h | test("^(127\\.|localhost$|\\[?::1)")) as $loop
      | "- \(.name): \(if $u == "" then "FAIL: no gateway URL configured"
          elif ($p.s == "http" or $p.s == "ws") and ($loop | not) then "FAIL: plain \($p.s):// to a remote host (use the Tailscale Serve https/wss URL)"
          else "ok (\($p.s)://)" end)\(if .adapterType == "openclaw_gateway" and ((.adapterConfig | has("devicePrivateKeyPem")) | not) then " · WARN: no persisted device key; every run may need pairing" else "" end)"' "$WORK/agents.json")"
  if [[ -n "$gw" ]]; then
    echo "## Gateway agents"; echo; printf '%s\n' "$gw"; echo
  fi
  local rec
  rec="$(for f in "$WORK"/recovery/*.json; do
          [[ -f "$f" ]] || continue
          iid="$(basename "$f" .json)"
          ident="$(jq -r --arg i "$iid" '.[] | select(.id == $i) | .identifier // "issue"' "$WORK/issues.json")"
          jq -r --arg ident "$ident" 'select(.active != null) | .active
             | "- \($ident): \(.kind) (cause: \(.cause // "?")). Next: \((.nextAction // "") | tostring | .[0:200])"' "$f"
        done)"
  if [[ -n "$rec" ]]; then
    echo "## Recovery actions waiting on someone"; echo; printf '%s\n' "$rec"; echo
  fi
  if [[ -f "$WORK/codex-auth.json" ]]; then
    echo "## Codex auth signal"
    echo
    jq -r '"- codex_local credentials on the board host: \(.status // "unknown")\(if .status == "absent" then " (run `codex login` as the service user)" else "" end)"' "$WORK/codex-auth.json"
    echo
  fi
  if [[ -n "$SERVER_LOG" ]]; then
    echo "## Server log"
    echo
    if [[ -r "$SERVER_LOG" ]]; then
      local epipe
      epipe="$(grep -c 'Error: write EPIPE' "$SERVER_LOG" || true)"
      if [[ "${epipe:-0}" -gt 0 ]]; then
        echo "- CRITICAL: server crashed on stdin EPIPE ${epipe} time(s): upstream bug (unhandled child stdin error). launchd restarts it; in-flight runs end as process_lost. Re-wake them."
      else
        echo "- no EPIPE crashes found"
      fi
    else
      echo "- WARN: cannot read $SERVER_LOG"
    fi
    echo
  fi
  echo "## Appendix: API calls"
  echo
  sed 's/^/- /' "$CALLS"
}

# Redact before anything leaves the machine: home paths, tailnet names, IPs
# (loopback kept), UUIDs, bearer tokens and common secret shapes.
redact() {
  sed -E \
    -e 's#/(Users|home)/[^/ "]+#<home>#g' \
    -e 's#[A-Za-z0-9-]+\.tail[0-9a-f]+\.ts\.net#<host>#g' \
    -e 's#127\.0\.0\.1#LOOPBACK_KEEP#g' \
    -e 's#(^|[^0-9.])([0-9]{1,3}\.){3}[0-9]{1,3}#\1<ip>#g' \
    -e 's#LOOPBACK_KEEP#127.0.0.1#g' \
    -e 's#[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}#<uuid>#g' \
    -e 's#(Bearer|bearer) [A-Za-z0-9._~+/=-]+#\1 <redacted>#g' \
    -e 's#(sk-[A-Za-z0-9_-]{10,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})#<redacted>#g'
}

report | redact > "$WORK/report.md"
FAILS="$(grep -c '^### FAIL' "$WORK/report.md" || true)"
CRIT="$(grep -c 'CRITICAL' "$WORK/report.md" || true)"
GWFAIL="$(grep -c ': FAIL:' "$WORK/report.md" || true)"
if [[ -n "$OUT" ]]; then cp "$WORK/report.md" "$OUT"; log "report written to $OUT"; else cat "$WORK/report.md"; fi
if [[ "$STRICT" == "1" && $((FAILS + CRIT + GWFAIL)) -gt 0 ]]; then exit 1; fi
exit 0
