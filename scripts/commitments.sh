#!/usr/bin/env bash
# Read-only report on commitments: what is overdue, what is due soon and at risk,
# and which work has stalled.
#
# A commitment is a project with a target date (Paperclip 2026.1005.0 has no due
# date on issues). An issue can carry its own deadline as a "Due: YYYY-MM-DD"
# line at the top of its description. The report flags:
#   - overdue projects and Due: issues
#   - projects due within the horizon that are at risk: no lead, nothing planned,
#     blocked issues, nothing in progress, or no activity for --stale-days
#   - in-progress/in-review issues idle for --stale-days, and blocked issues
#   - active projects with no target date or no lead
#
# Only HTTP GET is sent. An agent key works (the Chief of Staff runs this from a
# routine); PAPERCLIP_API_URL/KEY/COMPANY_ID are already set in agent runs.
#
# Usage: scripts/commitments.sh [--board-url URL] [--company-id ID] [--horizon 14]
#                               [--stale-days 3] [--today YYYY-MM-DD] [--out FILE] [--strict]
# Exit:  0, or 1 with --strict when anything is overdue or at risk.
set -euo pipefail
# shellcheck source=lib/common.sh
source "$(dirname "$0")/lib/common.sh"

BASE="${PAPERCLIP_API_URL:-http://127.0.0.1:${PAPERCLIP_PORT}}"
CO="${PAPERCLIP_COMPANY_ID:-}"
HORIZON=14; STALE=3; TODAY=""; OUT=""; STRICT=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --board-url) BASE="$2"; shift 2 ;;
    --company-id) CO="$2"; shift 2 ;;
    --horizon) HORIZON="$2"; shift 2 ;;
    --stale-days) STALE="$2"; shift 2 ;;
    --today) TODAY="$2"; shift 2 ;;
    --out) OUT="$2"; shift 2 ;;
    --strict) STRICT=1; shift ;;
    -h|--help) sed -n '2,19p' "$0"; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
done
BASE="${BASE%/}"
[[ "$HORIZON" =~ ^[0-9]+$ && "$STALE" =~ ^[0-9]+$ ]] || die "--horizon and --stale-days take whole days"
if [[ -n "$TODAY" ]]; then
  [[ "$TODAY" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] || die "--today takes YYYY-MM-DD"
else
  TODAY="$(date +%Y-%m-%d)"
fi
need curl
need jq

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
AUTH=()
if [[ -n "${PAPERCLIP_API_KEY:-}" ]]; then  # header file, not argv: ps can't show the key
  printf 'authorization: Bearer %s\n' "$PAPERCLIP_API_KEY" > "$WORK/auth.hdr"
  AUTH=(-H "@$WORK/auth.hdr")
fi

# The only way this script talks to the board.
api_get() { # path outfile -> returns 0 on HTTP 200
  local code
  code="$(curl -s -m 30 -o "$2" -w '%{http_code}' ${AUTH[@]+"${AUTH[@]}"} "$BASE$1" 2>/dev/null || true)"
  [[ "${code:-000}" == "200" ]] || { warn "HTTP ${code:-000} on GET ${1%%\?*}"; return 1; }
}

if [[ -z "$CO" ]]; then
  api_get /api/companies "$WORK/companies.json" || die "cannot list companies; pass --company-id"
  n="$(jq 'length' "$WORK/companies.json")"
  [[ "$n" == "1" ]] || die "board has $n companies; pass --company-id (one of: $(jq -r '[.[].name] | join(", ")' "$WORK/companies.json"))"
  CO="$(jq -r '.[0].id' "$WORK/companies.json")"
fi
api_get "/api/companies/$CO" "$WORK/company.json" || echo '{}' > "$WORK/company.json"
api_get "/api/companies/$CO/projects" "$WORK/projects.json" || die "cannot list projects"
api_get "/api/companies/$CO/agents" "$WORK/agents.json" || echo '[]' > "$WORK/agents.json"
# Issues come back newest first, at most 1000 per page.
offset=0; : > "$WORK/issues.jsonl"
while :; do
  api_get "/api/companies/$CO/issues?limit=1000&offset=$offset" "$WORK/page.json" || die "cannot list issues"
  jq -c '.[]' "$WORK/page.json" >> "$WORK/issues.jsonl"
  n="$(jq 'length' "$WORK/page.json")"
  [[ "$n" -lt 1000 ]] && break
  offset=$((offset + n))
done
jq -s '.' "$WORK/issues.jsonl" > "$WORK/issues.json"

# Midnight UTC of $TODAY plus 12h: stable "now" for day arithmetic, so a report
# run at 00:30 or 23:30 agrees with its date line.
NOWTS="$(jq -n --arg d "$TODAY" '($d | strptime("%Y-%m-%d") | mktime) + 43200')"

jq -r -n \
  --arg today "$TODAY" --argjson nowts "$NOWTS" \
  --argjson horizon "$HORIZON" --argjson stale "$STALE" \
  --slurpfile company "$WORK/company.json" \
  --slurpfile projects "$WORK/projects.json" \
  --slurpfile agents "$WORK/agents.json" \
  --slurpfile issues "$WORK/issues.json" '
def esc: tostring | gsub("[\r\n]+"; " ") | gsub("\\|"; "\\|");
def ts: if . == null then null else (.[0:19] + "Z" | fromdateiso8601) end;
def day: try (strptime("%Y-%m-%d") | mktime) catch null;
def idle($t): if $t == null then null else ((($nowts - $t) / 86400) | floor) end;
def ago($t): idle($t) as $d
  | if $d == null then "never" elif $d <= 0 then "today" elif $d == 1 then "1 day ago" else "\($d) days ago" end;
def plural($n; $w): "\($n) \($w)\(if $n == 1 then "" else "s" end)";
def table($head; $rows):
  if ($rows | length) == 0 then ["_None._"]
  else ["| " + ($head | join(" | ")) + " |", "|" + ($head | map("---") | join("|")) + "|"]
     + ($rows | map("| " + (map(esc) | join(" | ")) + " |"))
  end;

($company[0].name // "company") as $cname
| ($today | day) as $t0
| ($agents[0] | map({key: .id, value: .name}) | from_entries) as $an
| ($agents[0] | map(select(.status | IN("paused", "error", "terminated", "pending_approval")) | {key: .id, value: .status}) | from_entries) as $down
| def agent($id): ($an[$id] // "unknown agent") + (if $down[$id] then " (" + ($down[$id] | sub("_"; " ")) + ")" else "" end);
  def who: if .assigneeAgentId then agent(.assigneeAgentId)
           elif .assigneeUserId then "board user" else "unassigned" end;
  def recovery: {
    stranded_assigned_issue: "assignee cannot run (paused or failing); the board picks the next step",
    workspace_validation: "workspace check failed; run diagnose.sh",
    configuration_validation: "agent configuration is invalid; run diagnose.sh",
    active_run_watchdog: "run watchdog fired; run diagnose.sh",
    missing_disposition: "last run ended without done/blocked; the agent must say which",
    deliberate_wait_without_target: "waiting without saying on what",
    issue_graph_liveness: "its blocker chain is stuck; fix the blocking issue"
  }[.] // ("Paperclip recovery: " + .);
  def ref: (.identifier // "issue") + " " + (.title // "");
  def lastact: (.lastActivityAt // .updatedAt) | ts;
  def due: ((.description // "") | split("\n")[0:8]
            | map(capture("^[*_ \t]*[Dd]ue[*_ \t]*:[*_ \t]*(?<d>[0-9]{4}-[0-9]{2}-[0-9]{2})")) | first | .d) // null;
  def isopen: (.status == "done" or .status == "cancelled") | not;

  [ $issues[0][] | select(.hiddenAt == null) ] as $all
| ($projects[0] | map({key: .id, value: .name}) | from_entries) as $pn
| [ $projects[0][] | select(.status != "completed" and .status != "cancelled") | . as $p
    | [ $all[] | select(.projectId == $p.id) ] as $pi
    | ($pi | map(select(isopen))) as $open
    | { name: $p.name,
        lead: (if $p.leadAgentId then agent($p.leadAgentId) else null end),
        target: $p.targetDate,
        days: (if $p.targetDate then (($p.targetDate | day) as $d | if $d == null then null else (($d - $t0) / 86400 | floor) end) else null end),
        open: ($open | length),
        doing: ($open | map(select(.status == "in_progress" or .status == "in_review")) | length),
        blocked: ($open | map(select(.status == "blocked")) | length),
        stuckowner: ($open | map(select(.assigneeAgentId != null and $down[.assigneeAgentId] != null)) | length),
        done: ($pi | map(select(.status == "done")) | length),
        last: ([ $pi[] | lastact ] + [ $p.updatedAt | ts ] | map(select(. != null)) | max) }
    | .risks = [ if .lead == null then "no lead" else empty end,
                 if .open == 0 and .done == 0 then "no issues planned" else empty end,
                 if .blocked > 0 then plural(.blocked; "blocked issue") else empty end,
                 if .stuckowner > 0 then plural(.stuckowner; "issue") + " owned by a paused or failing agent" else empty end,
                 if .open > 0 and .doing == 0 then "nothing in progress" else empty end,
                 if .open > 0 and (idle(.last) // 0) >= $stale then "no activity for \(idle(.last)) days" else empty end ]
  ] as $rows
| ($rows | map(select(.days != null and .days < 0)) | sort_by(.days)) as $overdue
| ($rows | map(select(.days != null and .days >= 0 and .days <= $horizon)) | sort_by(.days)) as $soon
| ($soon | map(select(.risks | length > 0))) as $atrisk
| [ $all[] | select(isopen) | . as $i | (due) as $ds | select($ds != null)
    | ($ds | day) as $dd | select($dd != null)
    | (($dd - $t0) / 86400 | floor) as $days | select($days <= $horizon)
    | { ref: ($i | ref), project: ($pn[$i.projectId // ""] // "none"), owner: ($i | who),
        status: $i.status, due: $ds, days: $days,
        risks: [ if $i.status == "blocked" then "blocked" else empty end,
                 if $i.status == "backlog" or $i.status == "todo" then "not started" else empty end,
                 if ($i | who) == "unassigned" then "no owner" else empty end ] } ] | sort_by(.days) as $dueissues
| [ $all[] | select(.status == "in_progress" or .status == "in_review")
    | select((idle(lastact) // 0) >= $stale)
    | { ref: ref, owner: who, status: .status, idle: idle(lastact) } ] | sort_by(-.idle) as $stalled
| [ $all[] | select(.status == "blocked")
    | { ref: ref, owner: who, since: idle((.blockedTransitionAt // .updatedAt) | ts),
        unblock: (.unblockDescriptor as $u
          | if $u == null then (if .activeRecoveryAction.kind then (.activeRecoveryAction.kind | recovery) else "not stated" end)
            else ((if $u.owner == "board" then "board"
                   elif ($u.owner | type) == "object" and $u.owner.agentId then ($an[$u.owner.agentId] // "unknown agent")
                   else "board user" end) + ": " + ($u.action // "")) end) } ] | sort_by(-.since) as $blocked
| ($overdue | length) as $no
| ($dueissues | map(select(.days < 0)) | length) as $nio
| (if $no + $nio + ($atrisk | length) > 0 then "ATTENTION" else "ON TRACK" end) as $verdict
| [ "# Commitments: \($cname)",
    "",
    "As of \($today). Horizon \($horizon) days; idle after \($stale) days.",
    "",
    "**\($verdict)**: \(plural($no; "overdue project")), \(plural($nio; "overdue issue")), "
      + "\(plural($soon | length; "project")) due within \($horizon) days (\($atrisk | length) at risk), "
      + "\(plural($stalled | length; "stalled issue")), \(plural($blocked | length; "blocked issue")).",
    "",
    "## Overdue projects",
    "" ]
  + table(["Project", "Lead", "Target", "Late by", "Open", "Doing", "Blocked", "Done", "Last activity", "Risks"];
      $overdue | map([.name, (.lead // "none"), .target, plural(-.days; "day"), .open, .doing, .blocked, .done, ago(.last), (.risks | join("; "))]))
  + ["", "## Due within \($horizon) days", ""]
  + table(["Project", "Lead", "Target", "Due in", "Open", "Doing", "Blocked", "Done", "Last activity", "Risks"];
      $soon | map([.name, (.lead // "none"), .target, (if .days == 0 then "today" else plural(.days; "day") end), .open, .doing, .blocked, .done, ago(.last), (if (.risks | length) == 0 then "on track" else (.risks | join("; ")) end)]))
  + ["", "## Issue deadlines (Due: lines)", ""]
  + table(["Issue", "Project", "Owner", "Status", "Due", "When", "Risks"];
      $dueissues | map([.ref, .project, .owner, .status, .due,
        (if .days < 0 then "late by " + plural(-.days; "day") elif .days == 0 then "today" else "in " + plural(.days; "day") end),
        (.risks | join("; "))]))
  + ["", "## Stalled (in progress or in review, idle \($stale)+ days)", ""]
  + table(["Issue", "Owner", "Status", "Idle"]; $stalled | map([.ref, .owner, .status, plural(.idle; "day")]))
  + ["", "## Blocked", ""]
  + table(["Issue", "Owner", "Blocked for", "Unblock"]; $blocked | map([.ref, .owner, plural(.since // 0; "day"), .unblock]))
  + ["", "## Not tracked as commitments", ""]
  + [ "- Active projects with no target date: "
        + ($rows | map(select(.target == null) | .name) | if length == 0 then "none" else join(", ") + " (fine if ongoing; otherwise set one)" end),
      "- Active projects with no lead: " + ($rows | map(select(.lead == null) | .name) | if length == 0 then "none" else join(", ") end),
      "- Ready issues (todo) with no owner: " + ($all | map(select(.status == "todo" and .assigneeAgentId == null and .assigneeUserId == null)) | length | tostring) ]
  | .[]
' > "$WORK/report.md"

if [[ -n "$OUT" ]]; then cp "$WORK/report.md" "$OUT"; log "report written to $OUT"; else cat "$WORK/report.md"; fi
if [[ "$STRICT" == "1" ]] && grep -q '^\*\*ATTENTION\*\*' "$WORK/report.md"; then exit 1; fi
exit 0
