"""Tests for the package tooling. Run: python3 -m unittest discover -s tests"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from contextlib import redirect_stdout
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import pcyaml  # noqa: E402
import validate_company  # noqa: E402


def load_script(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


build_overlay = load_script("build_overlay", ROOT / "scripts" / "migrate" / "build-overlay.py")
import_company = load_script("import_company", ROOT / "scripts" / "import-company.py")
package_repos = load_script("package_repos", ROOT / "tools" / "package_repos.py")
normalize_export = load_script("normalize_export", ROOT / "tools" / "normalize_export.py")


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text).lstrip("\n"), encoding="utf-8")


class PcYamlTest(unittest.TestCase):
    def test_committed_files_read_the_same_by_paperclip(self):
        files = list((ROOT / "companies").rglob("*.md")) + list((ROOT / "companies").rglob(".paperclip.yaml"))
        self.assertTrue(files)
        for path in files:
            text = path.read_text(encoding="utf-8")
            raw = text if path.name == ".paperclip.yaml" else pcyaml.split_frontmatter(text)[0]
            if raw is None:
                continue
            with self.subTest(path=str(path.relative_to(ROOT))):
                self.assertEqual(pcyaml.parse(raw), yaml.safe_load(raw))

    def test_dump_round_trips(self):
        value = {"schema": "paperclip/v1", "n": 7, "flag": False, "empty": [], "none": None,
                 "agents": {"a": {"adapter": {"type": "claude_local"}, "tags": ["x", "y: z"]}},
                 "routines": {"r": {"triggers": [{"kind": "schedule", "cronExpression": "47 6 * * *"}]}}}
        text = pcyaml.dump(value)
        self.assertEqual(pcyaml.parse(text), value)
        self.assertEqual(yaml.safe_load(text), value)

    def test_divergent_yaml_is_detected(self):
        cases = {
            "four-space indent": "a:\n    b: 1\n",
            "list level with key": "skills:\n- review\n",
            "json document": '{\n  "schema": "paperclip/v1"\n}\n',
            "inline comment": "a: 1 # note\n",
            "block scalar": "a: |\n  line\n",
            "yaml-only boolean": "a: yes\n",
        }
        for label, raw in cases.items():
            with self.subTest(label):
                report = validate_company.Report(ROOT)
                validate_company.check_paperclip_reads_same(report, Path("x.yaml"), raw)
                self.assertTrue(report.errors, f"{label} should be flagged")


class ValidatorTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.pkg = self.tmp / "fleet"
        shutil.copytree(ROOT / "companies" / "fleet", self.pkg)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def errors(self):
        return validate_company.validate_package(self.pkg).errors

    def test_committed_package_is_valid(self):
        self.assertEqual(self.errors(), [])

    def test_rejects_secrets_and_tailnet_identifiers(self):
        agent = self.pkg / "agents" / "builder" / "AGENTS.md"
        agent.write_text(agent.read_text() + "\ntoken ghp_" + "a" * 36 + "\n")
        company = self.pkg / "COMPANY.md"
        company.write_text(company.read_text() + "\nhost box.tail1a2b3c.ts.net at 100.101.102.103\n")
        joined = "\n".join(self.errors())
        self.assertIn("GitHub token", joined)
        self.assertIn("tailnet MagicDNS name", joined)
        self.assertIn("tailnet IP", joined)

    def test_rejects_dangling_references(self):
        agent = self.pkg / "agents" / "builder" / "AGENTS.md"
        agent.write_text(agent.read_text().replace("reportsTo: chief-of-staff", "reportsTo: ghost"))
        task = self.pkg / "tasks" / "import-mack-work" / "TASK.md"
        task.write_text(task.read_text().replace("assignee: chief-of-staff", "assignee: nobody"))
        joined = "\n".join(self.errors())
        self.assertIn("reportsTo 'ghost'", joined)
        self.assertIn("assignee 'nobody'", joined)

    def test_routine_must_target_recurring_task(self):
        task = self.pkg / "tasks" / "daily-fleet-check" / "TASK.md"
        task.write_text(task.read_text().replace("recurring: true\n", ""))
        self.assertTrue(any("without 'recurring: true'" in e for e in self.errors()))


class OverlayTest(unittest.TestCase):
    def test_parse_checklist_open_items_with_metadata(self):
        with tempfile.TemporaryDirectory() as d:
            q = Path(d) / "TASK_QUEUE.md"
            write(q, """
                # Queue
                ## Active Items
                - [ ] Fix the thing. More detail here. | confidence:high | category:bug | extracted:2026-09-02 10:00
                - [x] Already done | category:ops
                - [>] In flight item | extracted:2026-03-01 00:00
                - [~] Skipped item
                ## Other
                - [ ] Plain backlog line
            """)
            items = build_overlay.parse_checklist(q)
        self.assertEqual([i["text"] for i in items],
                         ["Fix the thing. More detail here.", "In flight item", "Plain backlog line"])
        self.assertEqual(items[0]["meta"]["category"], "bug")
        self.assertEqual(items[0]["heading"], "Active Items")
        self.assertTrue(items[1]["in_progress"])
        self.assertEqual(build_overlay.title_for(items[0]["text"]), "Fix the thing.")

    def test_overlay_builds_and_validates(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            q = d / "TASK_QUEUE.md"
            write(q, """
                - [ ] New item | extracted:2026-09-02 10:00
                - [ ] Old item | extracted:2026-01-02 10:00
            """)
            projects = d / "projects.json"
            projects.write_text('[{"name": "Construct Pro", "repoUrl": "https://github.com/o/construct-pro"}]')
            out = d / "overlay"
            argv = ["build-overlay.py", "--projects", str(projects), "--checklist", f"{q}=intake",
                    "--since", "2026-08-01", "--out", str(out)]
            old_argv, sys.argv = sys.argv, argv
            try:
                with redirect_stdout(io.StringIO()):
                    self.assertEqual(build_overlay.main(), 0)
            finally:
                sys.argv = old_argv
            tasks = list(out.glob("projects/*/tasks/*/TASK.md"))
            self.assertEqual(len(tasks), 1)
            self.assertIn("New item", tasks[0].read_text())
            ext = pcyaml.parse((out / ".paperclip.yaml").read_text())
            self.assertEqual(ext["projects"]["construct-pro"]["workspaces"]["construct-pro"]["repoUrl"],
                             "https://github.com/o/construct-pro")
            self.assertEqual(validate_company.validate_package(out).errors, [])


class NormalizeExportTest(unittest.TestCase):
    def test_keeps_definitions_drops_runtime_state(self):
        with tempfile.TemporaryDirectory() as d:
            raw, out = Path(d) / "raw", Path(d) / "out"
            write(raw / "COMPANY.md", "---\nname: Fleet\nslug: fleet\n---\n\nx\n")
            write(raw / "README.md", "generated\n")
            write(raw / "agents" / "a" / "AGENTS.md",
                  '---\nname: "A"\nskills:\n  - "company/11111111-2222-3333-4444-555555555555/conv"\n'
                  '  - "paperclipai/paperclip/paperclip"\n---\n\nbody\n')
            write(raw / "skills" / "company" / "FLE" / "conv" / "SKILL.md",
                  '---\nname: "conv"\ndescription: "d"\nkey: "company/1111/conv"\nmetadata:\n'
                  '  skillKey: "company/1111/conv"\n  paperclip:\n    skillKey: "company/1111/conv"\n'
                  '    tags:\n      - "t"\n---\n\nskill body\n')
            write(raw / "skills" / "paperclipai" / "paperclip" / "paperclip" / "SKILL.md",
                  '---\nname: "paperclip"\ndescription: "bundled"\n---\n\nb\n')
            write(raw / "tasks" / "daily" / "TASK.md", '---\nname: "Daily"\nrecurring: true\n---\n\nrun\n')
            write(raw / "tasks" / "fle-1" / "TASK.md", '---\nname: "One-off"\n---\n\nwork\n')
            write(raw / ".paperclip.yaml",
                  'schema: "paperclip/v1"\ntasks:\n  daily:\n    priority: "low"\n  fle-1:\n    status: "todo"\n')
            with redirect_stdout(io.StringIO()):
                normalize_export.main(raw, out)

            self.assertFalse((out / "README.md").exists())
            self.assertFalse((out / "skills" / "paperclipai").exists())
            self.assertFalse((out / "tasks" / "fle-1").exists())
            self.assertTrue((out / "tasks" / "daily" / "TASK.md").exists())
            skill_fm = pcyaml.parse(pcyaml.split_frontmatter((out / "skills" / "conv" / "SKILL.md").read_text())[0])
            self.assertNotIn("key", skill_fm)
            self.assertNotIn("skillKey", skill_fm["metadata"])
            self.assertNotIn("skillKey", skill_fm["metadata"]["paperclip"])
            agent_fm = pcyaml.parse(pcyaml.split_frontmatter((out / "agents" / "a" / "AGENTS.md").read_text())[0])
            self.assertEqual(agent_fm["skills"], ["conv", "paperclipai/paperclip/paperclip"])
            ext = pcyaml.parse((out / ".paperclip.yaml").read_text())
            self.assertEqual(list(ext["tasks"]), ["daily"])


class ImportCompanyTest(unittest.TestCase):
    """Network calls are replaced; these check the decisions the script makes."""

    def run_main(self, argv, companies=(), preview=None, env=None):
        calls = []
        preview = preview or {"plan": {}, "envInputs": [
            {"key": "GH_TOKEN", "agentSlug": "builder", "kind": "secret", "requirement": "optional"}]}

        def fake_get(url, key):
            calls.append(("GET", url, None))
            if url.endswith("/api/companies"):
                return list(companies)
            return []

        def fake_post(url, body, key):
            calls.append(("POST", url, json.loads(json.dumps(body))))  # snapshot: body is mutated later
            if url.endswith("/preview"):
                return preview
            return {"company": {"name": "Fleet", "id": "c1", "action": "created"}}

        old = (import_company.get, import_company.post, sys.argv)
        import_company.get, import_company.post = fake_get, fake_post
        sys.argv = ["import-company.py", str(ROOT / "companies" / "fleet"), "--api-base", "http://x"] + argv
        env_backup = dict(os.environ)
        os.environ.update(env or {})
        devnull = open(os.devnull, "w")  # the validator subprocess needs a real fd
        try:
            with redirect_stdout(io.StringIO()), contextlib.redirect_stderr(devnull):
                try:
                    code = import_company.main()
                except SystemExit as exc:
                    code = exc.code
        finally:
            devnull.close()
            import_company.get, import_company.post, sys.argv = old
            os.environ.clear()
            os.environ.update(env_backup)
        return code, calls

    def test_refuses_duplicate_company_name(self):
        code, calls = self.run_main([], companies=[{"name": "Fleet", "id": "abc"}])
        self.assertEqual(code, 2)
        self.assertFalse(any(c[0] == "POST" and c[1].endswith("/api/companies/import") for c in calls))

    def test_secret_values_only_on_real_import(self):
        env = {"GH_TOKEN_BUILDER": "s3cret"}
        code, calls = self.run_main(["--secret-env", "agent:builder:GH_TOKEN=GH_TOKEN_BUILDER"], env=env)
        self.assertEqual(code, 0)
        real = [c for c in calls if c[1].endswith("/api/companies/import")]
        preview = [c for c in calls if c[1].endswith("/preview")]
        self.assertEqual(real[0][2]["secretValues"], {"agent:builder:GH_TOKEN": "s3cret"})
        self.assertTrue(real[0][2]["pauseAutomations"])
        self.assertNotIn("secretValues", preview[0][2])

    def test_refuses_unmet_required_input(self):
        preview = {"plan": {}, "envInputs": [
            {"key": "API_KEY", "agentSlug": "builder", "kind": "secret", "requirement": "required"}]}
        code, calls = self.run_main([], preview=preview)
        self.assertEqual(code, 2)
        self.assertFalse(any(c[1].endswith("/api/companies/import") for c in calls))

    def test_include_keys_are_explicit(self):
        code, calls = self.run_main(["--company-id", "c1", "--include", "projects,issues", "--collision", "skip"])
        body = [c for c in calls if c[1].endswith("/api/companies/import")][0][2]
        self.assertEqual(body["include"], {"agents": False, "company": False, "issues": True,
                                           "projects": True, "skills": False})


class PackageReposTest(unittest.TestCase):
    def test_lists_workspace_repo_urls(self):
        self.assertEqual(package_repos.repo_urls(ROOT / "companies" / "fleet"),
                         ["https://github.com/mfethe1/paperclip"])


class CliTest(unittest.TestCase):
    def test_validator_runs_without_pyyaml(self):
        with tempfile.TemporaryDirectory() as d:
            venv = Path(d) / "bare"
            made = subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(venv)],
                                  capture_output=True)
            if made.returncode != 0:
                self.skipTest("venv unavailable")
            bare = venv / "bin" / "python"
            r = subprocess.run([str(bare), "-I", str(ROOT / "tools" / "validate_company.py")],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("PyYAML not installed", r.stderr)

    def test_validator_cli_exit_codes(self):
        ok = subprocess.run([sys.executable, str(ROOT / "tools" / "validate_company.py")],
                            capture_output=True, text=True)
        self.assertEqual(ok.returncode, 0, ok.stdout + ok.stderr)


if __name__ == "__main__":
    unittest.main()
