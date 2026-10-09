#!/usr/bin/env bash
# Inventory git work that exists only on this host: uncommitted changes, commits
# not on any remote, branches without an upstream, and stashes.
#
# Read-only. Never fetches, pushes, or changes a repo. Uses the remote-tracking
# refs already on disk, so "not on any remote" is as of each repo's last fetch.
# Writes a markdown report to migration/out/ (gitignored) and prints a summary.
#
# Usage: scripts/migrate/inventory-local-work.sh [ROOT ...]     (default: $HOME)
# Env:   MAXDEPTH=5  how deep to look for repos under each root
set -euo pipefail
# shellcheck source=../lib/common.sh
source "$(dirname "$0")/../lib/common.sh"

MAXDEPTH="${MAXDEPTH:-5}"
[[ $# -gt 0 ]] || set -- "$HOME"
HOST_ALIAS="$(hostname -s 2>/dev/null || hostname)"
OUT_DIR="$REPO_ROOT/migration/out"
mkdir -p "$OUT_DIR"
REPORT="$OUT_DIR/inventory-${HOST_ALIAS}-$(date +%Y%m%d-%H%M).md"

# Strip credentials from remote URLs before they reach the report.
clean_url() { sed -E 's#(https?://)[^/@]+@#\1#'; }

# Find repo roots (a .git dir or a worktree's .git file), skipping bulky trees.
find_repos() {
  find "$@" -maxdepth "$MAXDEPTH" \
    \( -name node_modules -o -name Library -o -name .Trash -o -name .cache \
       -o -name target -o -name .venv -o -name venv -o -name .cargo -o -name .rustup \
       -o -name .npm -o -name .pnpm-store -o -name Pictures -o -name Music -o -name Movies \) -prune \
    -o -name .git -print 2>/dev/null \
  | sed 's#/\.git$##' | sort -u
}

# macOS privacy controls (TCC) silently hide these folders from Terminal unless it has
# Full Disk Access; list what couldn't be read instead of reporting "nothing found".
not_scanned=()
if [[ "$(uname -s)" == "Darwin" ]]; then
  for d in "$HOME/Documents" "$HOME/Desktop" "$HOME/Downloads"; do
    if [[ -d "$d" ]] && ! ls "$d" >/dev/null 2>&1; then
      warn "cannot read $d (grant Terminal Full Disk Access to include it)"
      not_scanned+=("$d")
    fi
  done
fi

{
  echo "# Local work inventory: ${HOST_ALIAS}"
  echo
  echo "Generated $(date -u +%Y-%m-%dT%H:%M:%SZ). Read-only scan; remote state is as of each repo's last fetch."
  echo
  echo "| Repo | Branch | Dirty | Untracked | Ahead of upstream | Not on any remote | Branches w/o upstream | Stashes | Remote |"
  echo "|---|---|---:|---:|---:|---:|---:|---:|---|"
} > "$REPORT"

total=0; flagged=0
while IFS= read -r repo; do
  [[ -n "$repo" ]] || continue
  git -C "$repo" rev-parse --is-inside-work-tree >/dev/null 2>&1 || continue
  total=$((total + 1))
  branch="$(git -C "$repo" symbolic-ref --quiet --short HEAD 2>/dev/null || echo "(detached)")"
  dirty="$(git -C "$repo" status --porcelain --untracked-files=no 2>/dev/null | wc -l | tr -d ' ')"
  untracked="$(git -C "$repo" status --porcelain 2>/dev/null | grep -c '^??' || true)"
  ahead="-"
  if git -C "$repo" rev-parse --abbrev-ref '@{upstream}' >/dev/null 2>&1; then
    ahead="$(git -C "$repo" rev-list --count '@{upstream}..HEAD' 2>/dev/null || echo '?')"
  fi
  if [[ -n "$(git -C "$repo" remote 2>/dev/null)" ]]; then
    local_only="$(git -C "$repo" rev-list --count --branches --not --remotes 2>/dev/null || echo '?')"
  else
    local_only="$(git -C "$repo" rev-list --count --branches 2>/dev/null || echo '?') (no remote)"
  fi
  no_upstream="$(git -C "$repo" for-each-ref --format='%(upstream)' refs/heads 2>/dev/null | grep -c '^$' || true)"
  stashes="$(git -C "$repo" stash list 2>/dev/null | wc -l | tr -d ' ')"
  remote="$(git -C "$repo" remote get-url origin 2>/dev/null | clean_url || true)"
  # shellcheck disable=SC2088  # literal ~ for display only
  case "$repo" in "$HOME"/*) rel="~/${repo#"$HOME"/}" ;; *) rel="$repo" ;; esac

  if [[ "$dirty" != "0" || "$untracked" != "0" || ( "$ahead" != "-" && "$ahead" != "0" ) \
        || "$local_only" != "0" || "$stashes" != "0" ]]; then
    flagged=$((flagged + 1))
    echo "| \`$rel\` | \`$branch\` | $dirty | $untracked | $ahead | $local_only | $no_upstream | $stashes | ${remote:-none} |" >> "$REPORT"
  fi
done < <(find_repos "$@")

{
  echo
  echo "Scanned $total repos/worktrees; $flagged have work that is not safely on a remote."
  if [[ ${#not_scanned[@]} -gt 0 ]]; then
    echo
    echo "**Not scanned** (macOS privacy controls; grant Terminal Full Disk Access and re-run):"
    for d in "${not_scanned[@]}"; do echo "- ~${d#"$HOME"}"; done
  fi
  echo
  echo "Next: one Paperclip issue per flagged repo (project = the repo's project). Decide per"
  echo "branch: push, archive, or discard. Pushing is the owner's call. Some branches"
  echo "(brand/private) must never go to a public remote."
} >> "$REPORT"

log "scanned $total repos/worktrees; $flagged need attention"
log "report: $REPORT"
