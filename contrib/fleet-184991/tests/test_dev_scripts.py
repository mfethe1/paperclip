"""Persistent lifecycle regressions for the sanitized dev start/stop scripts.

Real subprocess coverage, no mocks: the stop script must terminate only the
exact recorded PID/start-time identity, keep every other process alive
(including one named like a Paperclip server), fail closed on malformed
records, and treat a missing record as a no-op. The start script must refuse
to launch without an explicit secret and must record identity with the same
LC_ALL=C normalization the stop script verifies.
"""

import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STOP = ROOT / "scripts" / "paperclip-dev-stop.sh"
START = ROOT / "scripts" / "paperclip-dev-start.sh"


class DevScriptCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(
            dir=Path.home() / ".hermes/cache/scratch"
        )
        self.repo = Path(self.tmp.name)
        self.pid_file = self.repo / ".paperclip_server.pid"
        self.procs = []
        self.env = {**os.environ, "PAPERCLIP_REPO_DIR": str(self.repo)}

    def tearDown(self):
        for proc in self.procs:
            if proc.poll() is None:
                proc.kill()
        for proc in self.procs:
            proc.wait(timeout=10)
        self.tmp.cleanup()

    def spawn(self, *argv):
        proc = subprocess.Popen(argv if argv else ["sleep", "60"])
        self.procs.append(proc)
        return proc

    def lstart(self, pid):
        return subprocess.run(
            ["ps", "-o", "lstart=", "-p", str(pid)],
            env={**os.environ, "LC_ALL": "C"},
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    def record(self, pid, start, newline="\n"):
        self.pid_file.write_text(f"{pid}\t{start}{newline}")

    def run_stop(self):
        return subprocess.run(
            ["bash", str(STOP)],
            env=self.env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

    def assert_alive(self, proc):
        self.assertIsNone(proc.poll(), f"PID {proc.pid} must survive")

    def assert_stopped(self, proc):
        proc.wait(timeout=10)
        self.assertIsNotNone(proc.poll(), f"PID {proc.pid} must be stopped")


class StopLifecycleTests(DevScriptCase):
    def test_matching_record_stops_only_the_recorded_process(self):
        owned = self.spawn()
        unrelated = self.spawn()
        self.record(owned.pid, self.lstart(owned.pid))
        result = self.run_stop()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_stopped(owned)
        self.assert_alive(unrelated)
        self.assertFalse(self.pid_file.exists())

    def test_stale_record_wrong_identity_keeps_process(self):
        reused = self.spawn()
        bystander = self.spawn()
        self.record(reused.pid, "Wed Jan  1 00:00:00 2020")
        result = self.run_stop()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_alive(reused)
        self.assert_alive(bystander)
        self.assertFalse(self.pid_file.exists())

    def test_pid_reuse_simulation_never_kills_reused_pid(self):
        first = self.spawn()
        stale_start = self.lstart(first.pid)
        first.terminate()
        first.wait(timeout=10)
        # Guarantee the replacement has a different kernel start identity.
        boundary = int(time.time())
        while int(time.time()) <= boundary:
            time.sleep(0.02)
        reused = self.spawn()
        self.assertNotEqual(self.lstart(reused.pid), stale_start)
        self.record(reused.pid, stale_start)
        result = self.run_stop()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_alive(reused)

    def test_malformed_records_fail_closed(self):
        live = self.spawn()
        real_start = self.lstart(live.pid)
        cases = {
            "non-numeric pid": f"not-a-pid\t{real_start}\n",
            "partial pid": f"12x\t{real_start}\n",
            "empty start": f"{live.pid}\t\n",
            "missing start field": f"{live.pid}\n",
            "empty record": "",
        }
        for label, content in cases.items():
            with self.subTest(label=label):
                self.pid_file.write_text(content)
                result = self.run_stop()
                self.assertNotEqual(result.returncode, 0, label)
                self.assertIn("refusing to signal anything", result.stderr)
                self.assert_alive(live)
                # Fail closed: the malformed record is preserved, never acted on.
                self.assertTrue(self.pid_file.exists(), label)
                self.assertEqual(self.pid_file.read_text(), content)

    def test_missing_record_is_noop(self):
        self.assertFalse(self.pid_file.exists())
        result = self.run_stop()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")

    def test_dead_recorded_process_cleans_record_without_signal(self):
        gone = self.spawn()
        start = self.lstart(gone.pid)
        gone.terminate()
        gone.wait(timeout=10)
        self.record(gone.pid, start)
        result = self.run_stop()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.pid_file.exists())

    def test_whitespace_variants_still_match_identity(self):
        for label, wrap in (
            ("padded", lambda s: f"  {s}  "),
            ("no trailing newline", lambda s: s),
        ):
            with self.subTest(label=label):
                owned = self.spawn()
                self.record(
                    owned.pid,
                    wrap(self.lstart(owned.pid)),
                    newline="" if label == "no trailing newline" else "\n",
                )
                result = self.run_stop()
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assert_stopped(owned)
                self.assertFalse(self.pid_file.exists())

    def test_process_named_like_paperclip_server_survives(self):
        named = self.spawn(
            "bash", "-c", "exec -a @paperclipai/server sleep 60"
        )
        owned = self.spawn()
        self.record(owned.pid, self.lstart(owned.pid))
        result = self.run_stop()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_stopped(owned)
        # No pattern/pkill behavior may exist: a server-named process survives.
        self.assert_alive(named)


class ScriptContractTests(DevScriptCase):
    def test_scripts_have_no_pattern_based_kill(self):
        for script in (STOP, START):
            text = script.read_text()
            self.assertNotIn("pkill", text, script)
            self.assertNotIn("pgrep", text, script)
            self.assertNotIn("killall", text, script)

    def test_start_and_stop_share_timebase_normalization(self):
        stop = STOP.read_text()
        start = START.read_text()
        self.assertIn("LC_ALL=C ps -o lstart=", stop)
        self.assertIn("LC_ALL=C ps -o lstart=", start)
        trim_leading = '${1#"${1%%[![:space:]]*}"}'
        # Both scripts apply identical leading/trailing whitespace trimming.
        for token in ('%%[![:space:]]*', '##*[![:space:]]'):
            self.assertIn(token, stop)
            self.assertIn(token, start)
        self.assertNotIn(trim_leading, stop + start)  # guard: literal, not regex

    def test_start_refuses_to_launch_without_secret(self):
        env = {
            key: value
            for key, value in self.env.items()
            if key != "PAPERCLIP_AGENT_JWT_SECRET"
        }
        result = subprocess.run(
            ["bash", str(START)],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("PAPERCLIP_AGENT_JWT_SECRET", result.stderr)
        self.assertFalse(self.pid_file.exists())

    def test_start_refuses_without_repo_dir(self):
        env = {key: value for key, value in self.env.items() if key != "PAPERCLIP_REPO_DIR"}
        result = subprocess.run(
            ["bash", str(START)],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("PAPERCLIP_REPO_DIR", result.stderr)
        self.assertFalse(self.pid_file.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
