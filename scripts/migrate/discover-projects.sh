#!/usr/bin/env bash
# Write fleet/projects.json (gitignored) listing active, non-fork, non-archived repos
# as Paperclip project candidates. Edit the file (drop what isn't a real project,
# rename, merge) before building an overlay from it.
#
# Usage: scripts/migrate/discover-projects.sh [--owner mfethe1] [--days 60]
set -euo pipefail
# shellcheck source=../lib/common.sh
source "$(dirname "$0")/../lib/common.sh"

OWNER="mfethe1"
DAYS=60
while [[ $# -gt 0 ]]; do
  case "$1" in
    --owner) OWNER="$2"; shift 2 ;;
    --days) DAYS="$2"; shift 2 ;;
    -h|--help) sed -n '2,7p' "$0"; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
done

need gh "https://cli.github.com, then: gh auth login"
need jq
OUT="$REPO_ROOT/fleet/projects.json"
mkdir -p "$(dirname "$OUT")"

cutoff="$(date -u -v-"${DAYS}"d +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date -u -d "-${DAYS} days" +%Y-%m-%dT%H:%M:%SZ)"

gh repo list "$OWNER" --limit 300 --no-archived --source \
  --json name,url,description,pushedAt,isPrivate,defaultBranchRef \
| jq --arg cutoff "$cutoff" '
    [ .[]
      | select(.pushedAt >= $cutoff)
      | { slug: (.name | ascii_downcase | gsub("[^a-z0-9]+"; "-") | sub("^-+"; "") | sub("-+$"; "")),
          name: .name,
          description: (.description // ""),
          repoUrl: .url,
          defaultRef: (.defaultBranchRef.name // "main"),
          private: .isPrivate,
          pushedAt: .pushedAt }
    ] | sort_by(.pushedAt) | reverse' > "$OUT"

log "wrote $(jq length "$OUT") repos pushed since $cutoff to $OUT"
log "review it, then: scripts/migrate/build-overlay.py --projects $OUT --out exports/overlay"
