#!/usr/bin/env python3
"""Print every project workspace repoUrl declared in a company package's
.paperclip.yaml, one per line. Used by scripts/control-plane/preflight.sh to
check the board host can clone each repo (agent runs in a project fail with
workspace_validation_failed when the managed checkout can't be created).

Usage: tools/package_repos.py [companies/fleet]
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pcyaml  # noqa: E402


def repo_urls(package: Path) -> list[str]:
    ext_path = package / ".paperclip.yaml"
    if not ext_path.is_file():
        return []
    ext = pcyaml.parse(ext_path.read_text(encoding="utf-8"))
    urls: list[str] = []
    for project in (ext.get("projects") or {}).values():
        if not isinstance(project, dict):
            continue
        for ws in (project.get("workspaces") or {}).values():
            url = ws.get("repoUrl") if isinstance(ws, dict) else None
            if isinstance(url, str) and url and url not in urls:
                urls.append(url)
    return urls


if __name__ == "__main__":
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "companies" / "fleet"
    for u in repo_urls(root):
        print(u)
