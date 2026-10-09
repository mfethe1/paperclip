#!/usr/bin/env bash
# Export the live company from the board, normalize it, validate it, and show how it
# differs from what's committed in companies/<slug>. Nothing in companies/ is changed:
# review the diff and copy what you want, then open a PR.
#
# Run on any tailnet machine logged in to the board (paperclipai auth login).
# The raw export is written under exports/ (gitignored): it can contain project
# names and repo URLs for private repos.
#
# Usage: scripts/export-company.sh <company-id> [slug]        (slug defaults to "fleet")
set -euo pipefail
# shellcheck source=lib/common.sh
source "$(dirname "$0")/lib/common.sh"

COMPANY_ID="${1:-}"; SLUG="${2:-fleet}"
[[ -n "$COMPANY_ID" ]] || die "usage: $0 <company-id> [slug]   (find the id with: paperclipai company list)"

RAW="$REPO_ROOT/exports/${SLUG}-raw"
OUT="$REPO_ROOT/exports/${SLUG}"
rm -rf "$RAW"
mkdir -p "$REPO_ROOT/exports"

log "exporting company $COMPANY_ID"
pc company export "$COMPANY_ID" --out "$RAW" --include company,agents,projects,skills,tasks
python3 "$REPO_ROOT/tools/normalize_export.py" "$RAW" "$OUT"
python3 "$REPO_ROOT/tools/validate_company.py" "$OUT" \
  || die "normalized export failed validation (secrets, tailnet identifiers, or broken refs); fix on the board or by hand"

if [[ -d "$REPO_ROOT/companies/$SLUG" ]]; then
  log "differences vs companies/$SLUG (quoting-only changes are expected; Paperclip quotes every string):"
  diff -ru "$REPO_ROOT/companies/$SLUG" "$OUT" || true
fi
log "normalized export: $OUT"
log "copy reviewed changes into companies/$SLUG, run tools/validate_company.py, and open a PR"
