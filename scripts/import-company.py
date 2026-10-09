#!/usr/bin/env python3
"""Import a company package from this repo into Paperclip with every agent and
routine PAUSED.

`paperclipai company import` (2026.1005.0) has no flag for this and makes
imported routines live immediately; the fleet rule is that nothing recurring
starts without its own approval. This posts the same inline package the CLI
builds, plus `pauseAutomations: true`, to POST /api/companies/import.

Auth: board API key in $PAPERCLIP_API_KEY (not needed for a local_trusted dev
instance). Create a short-lived one with:
    paperclipai auth login --api-base "$PAPERCLIP_API_URL"
    export PAPERCLIP_API_KEY="$(paperclipai token board create --name company-import \
        --ttl-days 1 --json --api-base "$PAPERCLIP_API_URL" | jq -r .key.token)"

Usage:
    scripts/import-company.py companies/fleet --dry-run
    scripts/import-company.py companies/fleet
    scripts/import-company.py companies/fleet --company-id <uuid> --collision skip
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "tools"))
import pcyaml  # noqa: E402

INCLUDE_KEYS = {"company", "agents", "projects", "issues", "skills"}


def build_files(root: Path) -> dict[str, str]:
    files: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file() and not path.name.startswith(".DS_Store"):
            files[path.relative_to(root).as_posix()] = path.read_text(encoding="utf-8")
    return files


def get(url: str, api_key: str | None):
    req = urllib.request.Request(url, method="GET")
    if api_key:
        req.add_header("authorization", f"Bearer {api_key}")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        sys.exit(f"error: {exc.code} from {url}")


def existing_issue_titles(api: str, company_id: str, api_key: str | None) -> set[str]:
    titles: set[str] = set()
    offset, page = 0, 1000
    while True:
        rows = get(f"{api}/api/companies/{company_id}/issues?limit={page}&offset={offset}", api_key)
        titles.update(r.get("title", "") for r in rows)
        if len(rows) < page:
            return titles
        offset += page


def drop_existing_tasks(files: dict[str, str], titles: set[str]) -> int:
    """The server does not dedupe issues, so re-running an overlay would duplicate
    every task. Skip TASK.md files whose title already exists in the company."""
    dropped = 0
    for rel in [r for r in files if r.endswith("/TASK.md") or r == "TASK.md"]:
        raw, _ = pcyaml.split_frontmatter(files[rel])
        name = pcyaml.parse(raw).get("name") if raw is not None else None
        if isinstance(name, str) and name in titles:
            del files[rel]
            dropped += 1
    return dropped


def post(url: str, body: dict, api_key: str | None) -> dict:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("content-type", "application/json")
    if api_key:
        req.add_header("authorization", f"Bearer {api_key}")
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:2000]
        sys.exit(f"error: {exc.code} from {url}\n{detail}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("package", type=Path, help="package directory, e.g. companies/fleet")
    ap.add_argument("--api-base", default=os.environ.get("PAPERCLIP_API_URL", "http://127.0.0.1:3100"))
    ap.add_argument("--company-id", help="import into this existing company instead of creating one")
    ap.add_argument("--name", help="name for a new company (default: from COMPANY.md)")
    ap.add_argument("--collision", choices=["rename", "skip", "replace"], default="rename")
    ap.add_argument("--include", default="company,agents,projects,issues,skills",
                    help="comma-separated subset of company,agents,projects,issues,skills")
    ap.add_argument("--dry-run", action="store_true", help="preview only")
    ap.add_argument("--live", action="store_true",
                    help="do NOT pause imported agents/routines (needs its own approval)")
    args = ap.parse_args()

    root = args.package.resolve()
    if not (root / "COMPANY.md").is_file():
        sys.exit(f"error: {root} has no COMPANY.md")

    # Refuse to send anything the repo validator rejects (secrets, tailnet names, bad refs).
    # Validator output goes to stderr so --dry-run stdout stays pure JSON.
    check = subprocess.run([sys.executable, str(REPO_ROOT / "tools" / "validate_company.py"), str(root)],
                           stdout=sys.stderr)
    if check.returncode != 0:
        sys.exit("error: package failed validation; fix it before importing")

    # Send every key explicitly: an omitted key is treated as included by the
    # server, which would let an overlay overwrite the company's name/description.
    wanted = {k.strip() for k in args.include.split(",") if k.strip()}
    unknown = wanted - INCLUDE_KEYS
    if unknown:
        sys.exit(f"error: unknown --include values: {sorted(unknown)}")
    include = {k: k in wanted for k in sorted(INCLUDE_KEYS)}
    files = build_files(root)
    api = args.api_base.rstrip("/")
    key = os.environ.get("PAPERCLIP_API_KEY")
    if args.company_id and "issues" in wanted:
        dropped = drop_existing_tasks(files, existing_issue_titles(api, args.company_id, key))
        if dropped:
            print(f"skipping {dropped} task(s) whose title already exists in the company")
    target = ({"mode": "existing_company", "companyId": args.company_id} if args.company_id
              else {"mode": "new_company", "newCompanyName": args.name})
    body = {
        "source": {"type": "inline", "rootPath": root.name, "files": files,
                   "expectedFileCount": len(files)},
        "include": include,
        "target": target,
        "agents": "all",
        "collisionStrategy": args.collision,
    }

    if args.dry_run:
        path = (f"/api/companies/{args.company_id}/imports/preview" if args.company_id
                else "/api/companies/import/preview")
        result = post(api + path, body, key)
        print(json.dumps({k: result.get(k) for k in ("plan", "warnings", "errors") if k in result}, indent=2))
        return 1 if result.get("errors") else 0

    body["pauseAutomations"] = not args.live
    result = post(api + "/api/companies/import", body, key)
    company = result.get("company") or {}
    print(f"company: {company.get('name')} ({company.get('id')}) {company.get('action')}")
    for kind in ("agents", "projects", "skills"):
        for row in result.get(kind) or []:
            print(f"  {kind[:-1]:8} {row.get('action'):8} {row.get('slug')}")
    for warning in result.get("warnings") or []:
        print(f"  warning: {warning}")
    if not args.live:
        print("agents and routines were imported PAUSED; resume them from the board once approved.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
