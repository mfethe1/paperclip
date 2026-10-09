#!/usr/bin/env python3
"""Build an import overlay (a partial company package) from existing fleet work:

  * a project roster (JSON list, e.g. from discover-projects.sh) -> PROJECT.md +
    workspace repoUrl per project
  * markdown checklists (TASK_QUEUE.md, BACKLOG.md, ...) -> one TASK.md per OPEN
    item ("- [ ]" or "- [>]"), filed under a project you choose

The overlay is written to exports/ (gitignored: it can contain private repo names
and chat references) and imported into the EXISTING company with:

    scripts/import-company.py exports/overlay --company-id <id> \
        --include projects,issues --collision skip --dry-run

Nothing is assigned: imported issues land unassigned in backlog for the Chief of
Staff to triage. Every task body records where it came from.

Usage:
    build-overlay.py --projects fleet/projects.json \
        --checklist ~/openclaw-shared/workspace/TASK_QUEUE.md=intake \
        --since 2026-08-01 --out exports/overlay
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import pcyaml  # noqa: E402

ITEM_RE = re.compile(r"^\s*[-*]\s+\[(?P<mark>[ >xX~])\]\s+(?P<text>.+?)\s*$")
HEADING_RE = re.compile(r"^#{1,6}\s+(?P<h>.+?)\s*$")
SLUG_STRIP = re.compile(r"[^a-z0-9]+")


def slugify(text: str, limit: int = 48) -> str:
    slug = SLUG_STRIP.sub("-", text.lower()).strip("-")
    return slug[:limit].rstrip("-") or "item"


def yaml_str(value: str) -> str:
    # JSON strings are valid YAML scalars and handle quotes/colons safely.
    return json.dumps(value, ensure_ascii=False)


def parse_checklist(path: Path) -> list[dict]:
    """Open items only. TASK_QUEUE lines carry '| key:value' metadata."""
    items: list[dict] = []
    heading = ""
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if m := HEADING_RE.match(line):
            heading = m.group("h")
            continue
        m = ITEM_RE.match(line)
        if not m or m.group("mark") not in (" ", ">"):
            continue
        parts = [p.strip() for p in m.group("text").split(" | ")]
        meta = {}
        for part in parts[1:]:
            key, sep, val = part.partition(":")
            if sep and re.fullmatch(r"[a-z_]+", key):
                meta[key] = val.strip()
        items.append({
            "text": parts[0],
            "meta": meta,
            "heading": heading,
            "in_progress": m.group("mark") == ">",
            "line": lineno,
        })
    return items


def extracted_date(item: dict) -> date | None:
    raw = item["meta"].get("extracted", "")
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


def title_for(text: str) -> str:
    title = re.split(r"(?<=[.!?])\s|\s—\s", text, maxsplit=1)[0]
    return (title[:117] + "...") if len(title) > 120 else title


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--projects", type=Path, help="JSON list of {slug,name,description,repoUrl,status}")
    ap.add_argument("--checklist", action="append", default=[], metavar="FILE=PROJECT_SLUG",
                    help="markdown checklist and the project slug its items belong to (repeatable)")
    ap.add_argument("--since", type=date.fromisoformat,
                    help="skip TASK_QUEUE items whose 'extracted' date is older than this")
    ap.add_argument("--out", type=Path, default=Path("exports/overlay"))
    args = ap.parse_args()

    if args.out.exists():
        shutil.rmtree(args.out)
    (args.out / "projects").mkdir(parents=True)

    projects: dict[str, dict] = {}
    if args.projects:
        for row in json.loads(args.projects.read_text(encoding="utf-8")):
            slug = slugify(row.get("slug") or row["name"])
            projects[slug] = row
    for spec in args.checklist:
        _, sep, slug = spec.rpartition("=")
        if not sep or not slug:
            sys.exit(f"error: --checklist needs FILE=PROJECT_SLUG, got {spec!r}")
        projects.setdefault(slug, {"name": slug.replace("-", " ").title()})

    ext_projects: dict[str, dict] = {}
    for slug, row in projects.items():
        pdir = args.out / "projects" / slug
        (pdir / "tasks").mkdir(parents=True, exist_ok=True)
        desc = row.get("description") or ""
        (pdir / "PROJECT.md").write_text(
            f"---\nname: {yaml_str(row.get('name') or slug)}\nslug: {slug}\n"
            f"description: {yaml_str(desc)}\n---\n\n{desc or 'Imported from the fleet project roster.'}\n",
            encoding="utf-8")
        ext: dict = {"status": row.get("status") or "in_progress"}
        if row.get("repoUrl"):
            ext["workspaces"] = {slug: {
                "name": slug, "sourceType": "git_repo", "repoUrl": row["repoUrl"],
                **({"defaultRef": row["defaultRef"]} if row.get("defaultRef") else {}),
                "isPrimary": True,
            }}
        ext_projects[slug] = ext

    counts: dict[str, int] = {}
    skipped_old = 0
    seen: set[str] = set()
    for spec in args.checklist:
        file_str, _, slug = spec.rpartition("=")
        path = Path(file_str).expanduser()
        for item in parse_checklist(path):
            when = extracted_date(item)
            if args.since and when and when < args.since:
                skipped_old += 1
                continue
            digest = hashlib.sha1(f"{path.name}:{item['text']}".encode()).hexdigest()[:8]
            tslug = f"{slugify(title_for(item['text']), 40)}-{digest}"
            if tslug in seen:
                continue
            seen.add(tslug)
            source_lines = [f"- Imported from `{path.name}` line {item['line']}"
                            + (f", section \"{item['heading']}\"" if item["heading"] else "")]
            for key in ("category", "confidence", "extracted", "source"):
                if key in item["meta"]:
                    source_lines.append(f"- {key}: {item['meta'][key]}")
            if item["in_progress"]:
                source_lines.append("- Was marked in progress (`[>]`) in the source queue; confirm the owner before reassigning.")
            body = (f"{item['text']}\n\n## Source\n\n" + "\n".join(source_lines) +
                    "\n\nTriage: confirm this is still wanted, write acceptance criteria, "
                    "then assign it or close it with a reason.\n")
            tdir = args.out / "projects" / slug / "tasks" / tslug
            tdir.mkdir(parents=True)
            (tdir / "TASK.md").write_text(
                f"---\nname: {yaml_str(title_for(item['text']))}\nslug: {tslug}\nproject: {slug}\n---\n\n{body}",
                encoding="utf-8")
            counts[slug] = counts.get(slug, 0) + 1

    (args.out / "COMPANY.md").write_text(
        "---\nschema: agentcompanies/v1\nname: Fleet import overlay\nslug: fleet-import-overlay\n"
        "description: Projects and backlog imported from existing fleet queues. Import into the existing company only.\n"
        "---\n\nGenerated by scripts/migrate/build-overlay.py. Not committed.\n", encoding="utf-8")
    ext_doc = {"schema": "paperclip/v1", "schemaVersion": 7, "projects": ext_projects}
    (args.out / ".paperclip.yaml").write_text(pcyaml.dump(ext_doc), encoding="utf-8")

    print(f"overlay written to {args.out}")
    print(f"  projects: {len(projects)}")
    for slug, n in sorted(counts.items()):
        print(f"  tasks in {slug}: {n}")
    if skipped_old:
        print(f"  skipped {skipped_old} item(s) extracted before {args.since}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
