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

    def test_project_owner_needs_lead_and_dates_must_parse(self):
        ext = self.pkg / ".paperclip.yaml"
        text = ext.read_text().replace("    leadAgentSlug: chief-of-staff\n", "", 1)
        text = text.replace("    leadAgentSlug: fleet-ops\n", "    leadAgentSlug: fleet-ops\n    targetDate: \"2026-13-01\"\n", 1)
        ext.write_text(text.replace("status: in_progress", "status: active", 1))
        joined = "\n".join(self.errors())
        self.assertIn("projects.intake.leadAgentSlug must be 'chief-of-staff'", joined)
        self.assertIn("targetDate '2026-13-01' is not a YYYY-MM-DD date", joined)
        self.assertIn("status 'active' is not one of", joined)

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
            projects.write_text('[{"name": "Construct Pro", "repoUrl": "https://github.com/o/construct-pro",'
                                ' "targetDate": "2026-11-30", "lead": "builder"}]')
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
            self.assertEqual(ext["projects"]["construct-pro"]["targetDate"], "2026-11-30")
            self.assertEqual(ext["projects"]["construct-pro"]["leadAgentSlug"], "builder")
            self.assertEqual(validate_company.validate_package(out).errors, [])


class CardsOverlayTest(unittest.TestCase):
    def test_cards_map_status_skip_closed_and_validate(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            cards = d / "cards.json"
            cards.write_text(json.dumps([
                {"title": "Wire alerts", "body": "Link issues.", "status": "ready",
                 "project": "fleet-operations", "priority": "high", "source": "kanban:ops/42"},
                {"title": "Finished", "status": "done"},
                {"title": "Raw idea | with: punctuation", "status": "triage"},
                {"title": "Was running", "status": "running", "priority": "urgent"},
            ]))
            out = d / "overlay"
            old_argv, sys.argv = sys.argv, ["build-overlay.py", "--cards", str(cards), "--out", str(out)]
            try:
                with redirect_stdout(io.StringIO()):
                    self.assertEqual(build_overlay.main(), 0)
            finally:
                sys.argv = old_argv
            ext = pcyaml.parse((out / ".paperclip.yaml").read_text())
            statuses = sorted((v["status"], v.get("priority", "")) for v in ext["tasks"].values())
            self.assertEqual(statuses, [("backlog", ""), ("todo", ""), ("todo", "high")])
            texts = "\n".join(p.read_text() for p in out.glob("projects/*/tasks/*/TASK.md"))
            self.assertIn("Imported from kanban:ops/42", texts)
            self.assertIn("Status there: `running`", texts)
            self.assertNotIn("Finished", texts)
            self.assertTrue((out / "projects" / "fleet-operations" / "PROJECT.md").is_file())
            self.assertEqual(validate_company.validate_package(out).errors, [])

    def test_unknown_card_status_is_an_error(self):
        with tempfile.TemporaryDirectory() as d:
            cards = Path(d) / "cards.json"
            cards.write_text(json.dumps([{"title": "x", "status": "someday"}]))
            with self.assertRaises(ValueError):
                build_overlay.load_cards(cards)


class HermesHostScriptsTest(unittest.TestCase):
    """enable-hermes-api.sh and the dotenv helpers, against a throwaway HERMES_HOME."""

    BASH = os.environ.get("TEST_BASH", "bash")

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.env_file = self.tmp / ".env"
        self.env_file.write_text('OPENROUTER_API_KEY=sk-or-x\nexport API_SERVER_HOST="0.0.0.0"\n')
        self.env = {**os.environ, "HERMES_HOME": str(self.tmp), "HOME": str(self.tmp)}

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def sh(self, *args, stdin=None):
        return subprocess.run([self.BASH, *args], capture_output=True, text=True, env=self.env,
                              input=stdin, timeout=60, cwd=ROOT)

    def values(self):
        return dict(l.split("=", 1) for l in self.env_file.read_text().splitlines() if "=" in l)

    def test_dotenv_helpers(self):
        r = self.sh("-c", 'source scripts/lib/common.sh; f="$HERMES_HOME/.env"; '
                    'dotenv_get "$f" API_SERVER_HOST; dotenv_set "$f" API_SERVER_HOST <<<"127.0.0.1"; '
                    'dotenv_set "$f" NEW <<<"a=b c"; dotenv_get "$f" NEW')
        self.assertEqual(r.stdout.splitlines(), ["0.0.0.0", "a=b c"], r.stderr)
        self.assertEqual(self.values()["API_SERVER_HOST"], "127.0.0.1")
        self.assertNotIn("export", self.env_file.read_text())
        self.assertEqual(oct(self.env_file.stat().st_mode & 0o777), "0o600")

    def test_enable_keeps_key_and_never_prints_it(self):
        dry = self.sh("scripts/node/enable-hermes-api.sh", "--dry-run")
        self.assertEqual(dry.returncode, 0, dry.stderr)
        self.assertNotIn("API_SERVER_ENABLED", self.values())
        r = self.sh("scripts/node/enable-hermes-api.sh")
        self.assertEqual(r.returncode, 0, r.stderr)
        v = self.values()
        self.assertEqual((v["API_SERVER_ENABLED"], v["API_SERVER_HOST"], v["API_SERVER_PORT"]),
                         ("true", "127.0.0.1", "8642"))
        self.assertRegex(v["API_SERVER_KEY"], r"^[0-9a-f]{64}$")
        self.assertNotIn(v["API_SERVER_KEY"], r.stdout + r.stderr)
        self.assertEqual(v["OPENROUTER_API_KEY"], "sk-or-x")
        self.assertTrue(list(self.tmp.glob(".env.bak-*")))
        again = self.sh("scripts/node/enable-hermes-api.sh")
        self.assertEqual(self.values()["API_SERVER_KEY"], v["API_SERVER_KEY"])
        self.assertIn("kept the existing API_SERVER_KEY", again.stderr)
        off = self.sh("scripts/node/enable-hermes-api.sh", "--off")
        self.assertEqual(off.returncode, 0, off.stderr)
        self.assertEqual(self.values()["API_SERVER_ENABLED"], "false")
        self.assertEqual(self.values()["API_SERVER_KEY"], v["API_SERVER_KEY"])

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


def serve_fixtures(case, fix, routes):
    """Serve captured board responses on loopback; records every request method."""
    import http.server
    import re as _re
    import threading
    methods = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def _any(self):
            methods.append(self.command)
            path, _, query = self.path.partition("?")
            # A paged list: everything is on the first page.
            if "offset=" in query and "offset=0" not in query:
                return self._send(b"[]")
            for pattern, name in routes:
                m = _re.match(pattern, path)
                if m and self.command == "GET":
                    f = fix / name.format(*m.groups())
                    if f.is_file():
                        return self._send(f.read_bytes())
            self.send_response(404)
            self.send_header("content-length", "0")
            self.end_headers()

        def _send(self, body):
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        do_GET = do_POST = do_PATCH = do_PUT = do_DELETE = _any

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    case.addCleanup(srv.server_close)
    case.addCleanup(srv.shutdown)
    return f"http://127.0.0.1:{srv.server_address[1]}", methods


class DiagnoseTest(unittest.TestCase):
    """scripts/diagnose.sh against responses captured from a real 2026.1005.0 board
    (a Claude agent with no login and a Codex agent with no credentials)."""

    FIX = ROOT / "tests" / "fixtures" / "diagnose"

    def serve(self):
        return serve_fixtures(self, self.FIX, [
            (r"^/api/health$", "health.json"),
            (r"^/api/companies$", "companies.json"),
            (r"^/api/companies/[^/]+/agents$", "agents.json"),
            (r"^/api/companies/[^/]+/heartbeat-runs$", "runs.json"),
            (r"^/api/companies/[^/]+/issues$", "issues.json"),
            (r"^/api/companies/[^/]+/adapters/codex_local/auth-signal$", "codex-auth.json"),
            (r"^/api/heartbeat-runs/([^/]+)$", "runs/{0}.json"),
            (r"^/api/issues/([^/]+)/recovery-actions$", "recovery/{0}.json"),
        ])

    def test_report_groups_failures_and_stays_read_only(self):
        if not shutil.which("jq"):
            self.skipTest("jq not installed")
        url, methods = self.serve()
        cid = (self.FIX / "COMPANY_ID").read_text().strip()
        bash = os.environ.get("TEST_BASH", "bash")  # CI on macOS sets /bin/bash (3.2)
        r = subprocess.run([bash, str(ROOT / "scripts" / "diagnose.sh"), "--board-url", url,
                            "--company-id", cid, "--server-log", str(self.FIX / "server-epipe.log"), "--strict"],
                           capture_output=True, text=True, timeout=120)
        out = r.stdout
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertEqual(set(methods), {"GET"})
        self.assertIn("### FAIL: Claude Code is not logged in for the service user", out)
        self.assertIn("3 failed run(s)", out)
        self.assertIn("automatic retries exhausted", out)
        self.assertIn("### FAIL: Codex has no credentials for the service user", out)
        self.assertIn("CRITICAL: server crashed on stdin EPIPE", out)
        self.assertIn("WARN: database_backup_missing", out)
        self.assertIn("FLE-5: configuration_validation", out)
        self.assertNotIn("/Users/", out)
        self.assertNotIn("/home/", out)
        self.assertNotRegex(out, r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


class CommitmentsTest(unittest.TestCase):
    """scripts/commitments.sh against responses captured from a real 2026.1005.0 board:
    projects with target dates, issues in every state, Due: lines, paused agents."""

    FIX = ROOT / "tests" / "fixtures" / "commitments"

    def run_report(self, *args):
        if not shutil.which("jq"):
            self.skipTest("jq not installed")
        url, methods = serve_fixtures(self, self.FIX, [
            (r"^/api/companies/[^/]+$", "company.json"),
            (r"^/api/companies/[^/]+/projects$", "projects.json"),
            (r"^/api/companies/[^/]+/agents$", "agents.json"),
            (r"^/api/companies/[^/]+/issues$", "issues.json"),
        ])
        cid = (self.FIX / "COMPANY_ID").read_text().strip()
        bash = os.environ.get("TEST_BASH", "bash")
        r = subprocess.run([bash, str(ROOT / "scripts" / "commitments.sh"), "--board-url", url,
                            "--company-id", cid, *args], capture_output=True, text=True, timeout=60)
        self.assertEqual(set(methods), {"GET"})
        return r

    def test_flags_overdue_at_risk_and_stalled_work(self):
        r = self.run_report("--today", "2026-10-16", "--strict")
        out = r.stdout
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertIn("**ATTENTION**: 1 overdue project, 1 overdue issue, "
                      "4 projects due within 14 days (4 at risk)", out)
        self.assertIn("| Website Relaunch | Builder (paused) | 2026-10-12 | 4 days |", out)
        self.assertIn("| Grant Application | none | 2026-10-28 | 12 days | 0 | 0 | 0 | 0 |", out)
        self.assertIn("no lead; no issues planned", out)
        self.assertIn("owned by a paused or failing agent", out)
        # Due: lines, plain and bold; past the horizon and invalid dates are left out.
        self.assertRegex(out, r"FLE-15 Renew company domain \| Intake \| unassigned \| todo \| 2026-10-14 \| late by 2 days")
        self.assertIn("FLE-16 Send board deck | Intake | Chief of Staff (paused) | blocked | 2026-10-24 | in 8 days | blocked |", out)
        self.assertNotIn("Plan offsite", out)
        self.assertNotIn("Bad date", out)
        self.assertNotIn("Hiring Pipeline", out)
        # Blocked: the stated unblock, or Paperclip's recovery reason in plain words.
        self.assertIn("board: Approve the key rotation window", out)
        self.assertIn("assignee cannot run (paused or failing)", out)
        self.assertIn("Migrate blog posts \\| redirects", out)
        self.assertIn("| FLE-11 Verify migrated invoices | Verifier (paused) | in_review | 6 days |", out)

    def test_on_track_when_nothing_is_due(self):
        r = self.run_report("--today", "2026-09-01", "--strict")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("**ON TRACK**: 0 overdue projects, 0 overdue issues, 0 projects due within 14 days", r.stdout)


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
