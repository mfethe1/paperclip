#!/usr/bin/env bash
# Install the pre-commit hook: gitleaks on staged changes + company package validation.
# Git doesn't clone hooks, so run this on every fresh checkout.
set -euo pipefail
# shellcheck source=lib/common.sh
source "$(dirname "$0")/lib/common.sh"

hook="$(git -C "$REPO_ROOT" rev-parse --git-path hooks)/pre-commit"
cat > "$hook" <<'HOOK'
#!/usr/bin/env bash
set -euo pipefail
root="$(git rev-parse --show-toplevel)"
if ! command -v gitleaks >/dev/null 2>&1; then
  echo "pre-commit: gitleaks not installed (brew install gitleaks); refusing to commit unscanned" >&2
  exit 1
fi
gitleaks protect --staged --redact --no-banner
if git diff --cached --name-only | grep -q '^companies/'; then
  python3 "$root/tools/validate_company.py"
fi
HOOK
chmod +x "$hook"
log "installed $hook"
