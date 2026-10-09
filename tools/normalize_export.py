#!/usr/bin/env python3
"""Turn a raw `paperclipai company export` into the shape kept in companies/<slug>.

Keeps definitions, drops runtime state and noise:
  * keeps COMPANY.md, agents/, projects/, company-owned skills, recurring tasks
  * drops one-off issues (they are runtime state; the board is their home),
    Paperclip's bundled skills (skills/paperclipai/...), README.md and images/
  * flattens skills/company/<PREFIX>/<slug>/ to skills/<slug>/ and strips
    skill keys that embed the source company's database id

Usage: tools/normalize_export.py RAW_EXPORT_DIR OUT_DIR
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pcyaml  # noqa: E402

SKILL_ID_KEYS = ("key", "skillKey", "paperclipSkillKey")


def strip_skill_ids(fm: dict) -> dict:
    for k in SKILL_ID_KEYS:
        fm.pop(k, None)
    meta = fm.get("metadata")
    if isinstance(meta, dict):
        for k in SKILL_ID_KEYS:
            meta.pop(k, None)
        pc = meta.get("paperclip")
        if isinstance(pc, dict):
            for k in SKILL_ID_KEYS:
                pc.pop(k, None)
    return fm


def write_md(path: Path, fm: dict, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\n{pcyaml.dump(fm)}---\n\n{body.lstrip()}", encoding="utf-8")


def main(raw_dir: Path, out_dir: Path) -> int:
    if not (raw_dir / "COMPANY.md").is_file():
        sys.exit(f"error: {raw_dir} is not a company export (no COMPANY.md)")
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)

    shutil.copy2(raw_dir / "COMPANY.md", out_dir / "COMPANY.md")
    for sub in ("agents", "projects"):
        if (raw_dir / sub).is_dir():
            shutil.copytree(raw_dir / sub, out_dir / sub,
                            ignore=shutil.ignore_patterns("tasks"))

    # Agents reference company skills by "company/<company-uuid>/<slug>"; the
    # portable form is the bare slug (resolved against skills/<slug>/).
    for agent_md in sorted((out_dir / "agents").glob("*/AGENTS.md")) if (out_dir / "agents").is_dir() else []:
        raw, body = pcyaml.split_frontmatter(agent_md.read_text(encoding="utf-8"))
        if raw is None:
            continue
        fm = pcyaml.parse(raw)
        if isinstance(fm.get("skills"), list):
            fm["skills"] = [s.split("/")[-1] if isinstance(s, str) and s.startswith("company/") else s
                            for s in fm["skills"]]
            write_md(agent_md, fm, body)

    kept_skills = []
    for skill_md in sorted((raw_dir / "skills").rglob("SKILL.md")) if (raw_dir / "skills").is_dir() else []:
        rel = skill_md.relative_to(raw_dir / "skills").parts
        if rel[0] != "company":
            continue  # bundled/third-party skills are installed by Paperclip itself
        src_dir = skill_md.parent
        slug = src_dir.name
        dest_dir = out_dir / "skills" / slug
        shutil.copytree(src_dir, dest_dir)
        raw, body = pcyaml.split_frontmatter(skill_md.read_text(encoding="utf-8"))
        if raw is not None:
            write_md(dest_dir / "SKILL.md", strip_skill_ids(pcyaml.parse(raw)), body)
        kept_skills.append(slug)

    kept_tasks = []
    task_files = list(raw_dir.glob("tasks/*/TASK.md")) + list(raw_dir.glob("projects/*/tasks/*/TASK.md"))
    for task_md in sorted(task_files):
        raw, _ = pcyaml.split_frontmatter(task_md.read_text(encoding="utf-8"))
        fm = pcyaml.parse(raw) if raw is not None else {}
        if fm.get("recurring") is True:
            dest = out_dir / "tasks" / task_md.parent.name / "TASK.md"
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(task_md, dest)
            kept_tasks.append(task_md.parent.name)

    ext_path = raw_dir / ".paperclip.yaml"
    if ext_path.is_file():
        ext = pcyaml.parse(ext_path.read_text(encoding="utf-8"))
        if isinstance(ext.get("tasks"), dict):
            ext["tasks"] = {k: v for k, v in ext["tasks"].items() if k in kept_tasks}
            if not ext["tasks"]:
                del ext["tasks"]
        (out_dir / ".paperclip.yaml").write_text(pcyaml.dump(ext), encoding="utf-8")

    print(f"normalized export -> {out_dir}")
    print(f"  skills kept: {', '.join(kept_skills) or 'none'}")
    print(f"  recurring tasks kept: {', '.join(kept_tasks) or 'none'}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    sys.exit(main(Path(sys.argv[1]), Path(sys.argv[2])))
