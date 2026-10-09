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
    # re-running against a board that already has the company:
    scripts/import-company.py companies/fleet --company-id <uuid> --collision skip
    # bind secret env inputs at import (values read from the environment, never printed):
    GH_TOKEN_BUILDER=... scripts/import-company.py companies/fleet \
        --secret-env agent:builder:GH_TOKEN=GH_TOKEN_BUILDER
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


def existing_routine_titles(api: str, company_id: str, api_key: str | None) -> set[str]:
    rows = get(f"{api}/api/companies/{company_id}/routines", api_key)
    return {r.get("title", "") for r in rows if isinstance(r, dict)}


def company_name(files: dict[str, str]) -> str | None:
    raw, _ = pcyaml.split_frontmatter(files.get("COMPANY.md", ""))
    name = pcyaml.parse(raw).get("name") if raw is not None else None
    return name if isinstance(name, str) else None


def parse_secret_env(specs: list[str]) -> dict[str, str]:
    """SCOPE=ENVVAR pairs -> {scope: value}; scope as the server keys it, e.g.
    agent:builder:GH_TOKEN. Values come only from the environment."""
    values: dict[str, str] = {}
    for spec in specs:
        scope, sep, var = spec.rpartition("=")
        if not sep or not scope or not var:
            sys.exit(f"error: --secret-env needs SCOPE=ENVVAR, got {spec!r}")
        value = os.environ.get(var, "")
        if not value.strip():
            sys.exit(f"error: environment variable {var} (for {scope}) is unset or empty")
        values[scope] = value
    return values


def env_input_scope(entry: dict) -> str:
    # Mirrors envInputScopedKey() in the server's company-portability service.
    if entry.get("agentSlug"):
        return f"agent:{entry['agentSlug']}:{entry['key']}"
    if entry.get("projectSlug"):
        return f"project:{entry['projectSlug']}:{entry['key']}"
    return entry.get("key", "")


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
    ap.add_argument("--new-company", action="store_true",
                    help="create a new company even if one with the same name exists")
    ap.add_argument("--secret-env", action="append", default=[], metavar="SCOPE=ENVVAR",
                    help="bind a secret env input, e.g. agent:builder:GH_TOKEN=GH_TOKEN_BUILDER (repeatable)")
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
    secret_values = parse_secret_env(args.secret_env)

    # Creating a second company with the same name is almost never intended, and
    # the server allows it ("Fleet (2)"), duplicating every agent and routine.
    if not args.company_id and not args.new_company:
        name = args.name or company_name(files)
        for row in get(f"{api}/api/companies", key) or []:
            if isinstance(row, dict) and row.get("name") == name:
                print(f"error: company '{name}' already exists (id {row.get('id')}); re-run with "
                      f"--company-id {row.get('id')} --collision skip, or pass --new-company to create another",
                      file=sys.stderr)
                return 2

    # The server dedupes neither issues nor routines on import: skip tasks whose
    # title already exists as an issue or a routine.
    if args.company_id and "issues" in wanted:
        titles = existing_issue_titles(api, args.company_id, key) | existing_routine_titles(api, args.company_id, key)
        dropped = drop_existing_tasks(files, titles)
        if dropped:
            print(f"skipping {dropped} task(s) whose title already exists in the company", file=sys.stderr)
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
    preview_path = (f"/api/companies/{args.company_id}/imports/preview" if args.company_id
                    else "/api/companies/import/preview")
    preview = post(api + preview_path, body, key)
    env_inputs = [{"scope": env_input_scope(e), "kind": e.get("kind"), "requirement": e.get("requirement")}
                  for e in preview.get("envInputs") or []]

    if args.dry_run:
        out = {k: preview.get(k) for k in ("plan", "warnings", "errors") if k in preview}
        out["envInputs"] = env_inputs
        print(json.dumps(out, indent=2))
        return 1 if preview.get("errors") else 0

    # A required input with no value makes the server create an empty company and
    # then fail with 422; refuse up front instead.
    missing = [e["scope"] for e in env_inputs
               if e["requirement"] == "required" and e["scope"] not in secret_values]
    if missing:
        print("error: required env inputs have no value; pass --secret-env for: " + ", ".join(missing),
              file=sys.stderr)
        return 2
    unused = sorted(set(secret_values) - {e["scope"] for e in env_inputs})
    if unused:
        print(f"error: --secret-env scopes not declared by the package: {', '.join(unused)}", file=sys.stderr)
        return 2

    body["pauseAutomations"] = not args.live
    if secret_values:
        body["secretValues"] = secret_values
    result = post(api + "/api/companies/import", body, key)
    company = result.get("company") or {}
    print(f"company: {company.get('name')} ({company.get('id')}) {company.get('action')}")
    for kind in ("agents", "projects", "skills"):
        for row in result.get(kind) or []:
            print(f"  {kind[:-1]:8} {row.get('action'):8} {row.get('slug')}")
    for warning in result.get("warnings") or []:
        print(f"  warning: {warning}")
    if secret_values:
        print(f"bound {len(secret_values)} secret env input(s): {', '.join(sorted(secret_values))}")
    if not args.live:
        print("agents and routines were imported PAUSED; resume them from the board once approved.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
