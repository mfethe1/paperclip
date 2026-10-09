#!/usr/bin/env python3
"""Static checks for Agent Company packages under companies/.

Mirrors the rules Paperclip's importer applies (server/src/services/
company-portability.ts in paperclipai/paperclip) plus this repo's own
guardrails: no secret values, no machine-local paths, no tailnet hostnames.

Usage: python3 tools/validate_company.py [companies/<slug> ...]
Exit status is non-zero when any package has errors.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import date, datetime
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pcyaml  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent

# packages/shared/src/constants.ts AGENT_ROLES
AGENT_ROLES = {
    "ceo", "cto", "cmo", "cfo", "security", "engineer", "designer",
    "pm", "qa", "devops", "researcher", "general",
}

# Built-in adapter type keys (docs/adapters/overview.md).
ADAPTER_TYPES = {
    "claude_local", "codex_local", "gemini_local", "kimi_local",
    "opencode_local", "cursor", "pi_local", "grok_local", "hermes_local",
    "hermes_gateway", "openclaw_gateway", "process", "http",
}

SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

# Values that must never be committed. Patterns are deliberately broad.
SECRET_PATTERNS = [
    (re.compile(r"sk-ant-[A-Za-z0-9_-]{10,}"), "Anthropic key"),
    (re.compile(r"sk-[A-Za-z0-9]{20,}"), "OpenAI-style key"),
    (re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"), "GitHub token"),
    (re.compile(r"github_pat_[A-Za-z0-9_]{20,}"), "GitHub PAT"),
    (re.compile(r"tskey-[A-Za-z0-9-]{10,}"), "Tailscale auth key"),
    (re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"), "Slack token"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "private key"),
    (re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{35}\b"), "Telegram bot token"),
]

# Machine-local or tailnet-identifying values (repo is shareable; these live
# in gitignored fleet/hosts.yaml instead).
LOCAL_PATTERNS = [
    (re.compile(r"(?<![\w.])/Users/[A-Za-z0-9._-]+"), "macOS home path"),
    (re.compile(r"(?<![\w.])/home/[A-Za-z0-9._-]+"), "Linux home path"),
    (re.compile(r"[A-Za-z]:\\\\?Users\\\\?"), "Windows home path"),
    (re.compile(r"\b[a-z0-9-]+\.tail[0-9a-f]+\.ts\.net\b"), "tailnet MagicDNS name"),
    (re.compile(r"\b100\.(6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d{1,3}\.\d{1,3}\b"), "tailnet IP"),
]


def _normalize(value):
    if isinstance(value, dict):
        return {str(k): _normalize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_normalize(v) for v in value]
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def check_paperclip_reads_same(report: "Report", path: Path, raw: str) -> None:
    try:
        expected = _normalize(yaml.safe_load(raw) or {})
    except yaml.YAMLError as exc:
        report.error(path, f"invalid YAML: {exc}")
        return
    actual = _normalize(pcyaml.parse(raw))
    if expected != actual:
        report.error(path, "Paperclip's YAML parser reads this differently from standard YAML "
                     "(use 2-space block style, no |/> scalars, no inline comments, no multi-line {}/[])")


def parse_frontmatter(path: Path) -> tuple[dict, str]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---", 4)
    if end == -1:
        raise ValueError("unterminated frontmatter")
    data = yaml.safe_load(text[4:end]) or {}
    if not isinstance(data, dict):
        raise ValueError("frontmatter is not a mapping")
    return data, text[end + 4:].lstrip("\n")


class Report:
    def __init__(self, root: Path):
        self.root = root
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def error(self, where: Path | str, msg: str) -> None:
        self.errors.append(f"{self._rel(where)}: {msg}")

    def warn(self, where: Path | str, msg: str) -> None:
        self.warnings.append(f"{self._rel(where)}: {msg}")

    def _rel(self, where: Path | str) -> str:
        if isinstance(where, Path):
            try:
                return str(where.relative_to(REPO_ROOT))
            except ValueError:
                return str(where)
        return where


def slug_for(path: Path, fm: dict) -> str:
    return str(fm.get("slug") or path.parent.name)


def scan_text(report: Report, path: Path, strict: bool) -> None:
    text = path.read_text(encoding="utf-8", errors="replace")
    for pattern, label in SECRET_PATTERNS:
        if pattern.search(text):
            report.error(path, f"looks like it contains a {label}")
    for pattern, label in LOCAL_PATTERNS:
        if pattern.search(text):
            if strict:
                report.error(path, f"contains a {label}; keep it in fleet/hosts.json")
            else:
                report.warn(path, f"contains a {label}")


def validate_package(root: Path) -> Report:
    report = Report(root)
    company_md = root / "COMPANY.md"
    if not company_md.is_file():
        report.error(root, "missing COMPANY.md")
        return report

    # An overlay (no agents/) adds projects and backlog to an existing company. It
    # is generated into exports/ and never committed, so host identifiers in task
    # text are warnings there; secrets are always errors.
    overlay = not (root / "agents").is_dir()
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix in {".md", ".yaml", ".yml", ".json", ".sh"}:
            scan_text(report, path, strict=not overlay)
        if path.is_file() and path.suffix == ".md":
            text = path.read_text(encoding="utf-8")
            end = text.find("\n---\n", 4)
            if text.startswith("---\n") and end != -1:
                check_paperclip_reads_same(report, path, text[4:end])
    if (root / ".paperclip.yaml").is_file():
        check_paperclip_reads_same(report, root / ".paperclip.yaml",
                                   (root / ".paperclip.yaml").read_text(encoding="utf-8"))

    try:
        company, _ = parse_frontmatter(company_md)
    except (ValueError, yaml.YAMLError) as exc:
        report.error(company_md, f"bad frontmatter: {exc}")
        return report
    for field in ("name", "slug", "description", "schema"):
        if not company.get(field):
            report.error(company_md, f"missing required field '{field}'")
    if company.get("schema") not in (None, "agentcompanies/v1"):
        report.error(company_md, "schema must be agentcompanies/v1")
    if company.get("slug") and not SLUG_RE.match(str(company["slug"])):
        report.error(company_md, "slug must be lowercase kebab-case")

    agents: dict[str, dict] = {}
    for path in sorted(root.glob("agents/*/AGENTS.md")):
        try:
            fm, body = parse_frontmatter(path)
        except (ValueError, yaml.YAMLError) as exc:
            report.error(path, f"bad frontmatter: {exc}")
            continue
        slug = slug_for(path, fm)
        if slug in agents:
            report.error(path, f"duplicate agent slug '{slug}'")
        agents[slug] = fm
        if not SLUG_RE.match(slug):
            report.error(path, f"agent slug '{slug}' must be lowercase kebab-case")
        if not fm.get("name"):
            report.error(path, "missing 'name'")
        role = fm.get("role")
        if role is not None and role not in AGENT_ROLES:
            report.error(path, f"role '{role}' is not one of {sorted(AGENT_ROLES)}")
        if not body.strip():
            report.error(path, "empty instructions body")

    if not agents and not overlay:
        report.error(root, "package defines no agents")

    roots = [s for s, fm in agents.items() if fm.get("reportsTo") in (None, "")]
    if not overlay and len(roots) != 1:
        report.error(root, f"expected exactly one root agent (reportsTo: null), found {roots}")
    for slug, fm in agents.items():
        parent = fm.get("reportsTo")
        if parent and parent not in agents:
            report.error(root / "agents" / slug, f"reportsTo '{parent}' is not an agent in this package")
    # Cycle check.
    for slug in agents:
        seen, cur = set(), slug
        while cur:
            if cur in seen:
                report.error(root / "agents" / slug, "reportsTo chain has a cycle")
                break
            seen.add(cur)
            cur = agents.get(cur, {}).get("reportsTo")

    skills: set[str] = set()
    for path in sorted(root.glob("skills/*/SKILL.md")):
        try:
            fm, body = parse_frontmatter(path)
        except (ValueError, yaml.YAMLError) as exc:
            report.error(path, f"bad frontmatter: {exc}")
            continue
        name = fm.get("name")
        if not name or not fm.get("description"):
            report.error(path, "SKILL.md needs 'name' and 'description' (Agent Skills spec)")
        if name and name != path.parent.name:
            report.error(path, f"skill name '{name}' must match its directory '{path.parent.name}'")
        skills.add(path.parent.name)
        if not body.strip():
            report.error(path, "empty skill body")

    for slug, fm in agents.items():
        for skill in fm.get("skills") or []:
            if skill not in skills:
                report.warn(root / "agents" / slug, f"skill '{skill}' is not packaged here; it must exist in the company skill library")

    projects: set[str] = set()
    for path in sorted(root.glob("projects/*/PROJECT.md")):
        try:
            fm, _ = parse_frontmatter(path)
        except (ValueError, yaml.YAMLError) as exc:
            report.error(path, f"bad frontmatter: {exc}")
            continue
        slug = slug_for(path, fm)
        projects.add(slug)
        if not fm.get("name"):
            report.error(path, "missing 'name'")
        owner = fm.get("owner")
        if owner and owner not in agents:
            report.error(path, f"owner '{owner}' is not an agent in this package")

    tasks: dict[str, dict] = {}
    for path in sorted(list(root.glob("tasks/*/TASK.md")) + list(root.glob("projects/*/tasks/*/TASK.md"))):
        try:
            fm, body = parse_frontmatter(path)
        except (ValueError, yaml.YAMLError) as exc:
            report.error(path, f"bad frontmatter: {exc}")
            continue
        slug = slug_for(path, fm)
        if slug in tasks:
            report.error(path, f"duplicate task slug '{slug}'")
        tasks[slug] = fm
        if not fm.get("name"):
            report.error(path, "missing 'name'")
        assignee = fm.get("assignee")
        if assignee and assignee not in agents:
            report.error(path, f"assignee '{assignee}' is not an agent in this package")
        project = fm.get("project")
        if project and project not in projects:
            report.error(path, f"project '{project}' is not a project in this package")
        if not body.strip():
            report.error(path, "empty task description")

    ext_path = root / ".paperclip.yaml"
    if ext_path.is_file():
        try:
            ext = yaml.safe_load(ext_path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            report.error(ext_path, f"invalid YAML: {exc}")
            ext = {}
        if ext.get("schema") != "paperclip/v1":
            report.error(ext_path, "schema must be paperclip/v1")
        for slug, cfg in (ext.get("agents") or {}).items():
            if slug not in agents:
                report.error(ext_path, f"agents.{slug} has no matching AGENTS.md")
                continue
            adapter = (cfg or {}).get("adapter") or {}
            atype = adapter.get("type")
            if not atype:
                report.error(ext_path, f"agents.{slug}.adapter.type missing (importer would default to 'process')")
            elif atype not in ADAPTER_TYPES:
                report.error(ext_path, f"agents.{slug}.adapter.type '{atype}' is not a known adapter")
            for key, decl in ((cfg or {}).get("inputs") or {}).get("env", {}).items():
                if isinstance(decl, dict) and decl.get("kind") == "secret" and decl.get("default"):
                    report.error(ext_path, f"agents.{slug}.inputs.env.{key} is a secret with a default value")
        for slug in agents:
            if slug not in (ext.get("agents") or {}):
                report.error(ext_path, f"agent '{slug}' has no adapter config in .paperclip.yaml")
        for slug in (ext.get("projects") or {}):
            if slug not in projects:
                report.error(ext_path, f"projects.{slug} has no matching PROJECT.md")
        for slug, routine in (ext.get("routines") or {}).items():
            if slug not in tasks:
                report.error(ext_path, f"routines.{slug} has no matching TASK.md")
            elif not tasks[slug].get("recurring"):
                report.error(ext_path, f"routines.{slug} targets a task without 'recurring: true'")
            for trig in (routine or {}).get("triggers") or []:
                if trig.get("kind") == "schedule":
                    cron = str(trig.get("cronExpression", ""))
                    if len(cron.split()) != 5:
                        report.error(ext_path, f"routines.{slug} cronExpression '{cron}' is not 5 fields")
                    if not trig.get("timezone"):
                        report.error(ext_path, f"routines.{slug} schedule trigger needs a timezone")
    elif agents:
        report.error(root, "missing .paperclip.yaml (adapter types would default to 'process')")

    return report


def main(argv: list[str]) -> int:
    targets = [Path(a).resolve() for a in argv] or sorted(
        p.parent for p in (REPO_ROOT / "companies").glob("*/COMPANY.md")
    )
    if not targets:
        print("no company packages found under companies/")
        return 1
    failed = False
    for root in targets:
        report = validate_package(root)
        status = "FAIL" if report.errors else "ok"
        print(f"[{status}] {report._rel(root)}")
        for msg in report.errors:
            print(f"  error: {msg}")
        for msg in report.warnings:
            print(f"  warn:  {msg}")
        failed = failed or bool(report.errors)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
