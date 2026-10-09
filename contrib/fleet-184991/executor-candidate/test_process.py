"""Real subprocess probe/client tests; diagnostics only, never fleet acceptance."""

import hashlib
import json
import signal
import subprocess
import sys
import unittest
from pathlib import Path

import executor_fixtures as fixtures
from executor import (
    Denied,
    canonical,
    decode,
    validate_success,
)
from executor_fixtures import BASE, COMPANY, PROJECT, PUBLIC, RECEIPT
from probe_runner import run_bounded


class ProcessTests(fixtures.CandidateCase):
    def test_real_subprocess_artifact_not_model_qualification(self):
        self.ledger.admit(self.req)
        self.ledger.start(self.req["attempt"], 1)
        result = run_bounded(
            [
                sys.executable,
                "-c",
                "from pathlib import Path; Path('artifact.txt').write_text('actual artifact')",
            ],
            self.root,
        )
        self.assertEqual(result["exit_code"], 0)
        artifact = hashlib.sha256((self.root / "artifact.txt").read_bytes()).hexdigest()
        with self.assertRaises(Denied):
            self.ledger.finish(
                self.req["attempt"],
                1,
                "succeeded",
                exit_code=0,
                artifacts={"artifact.txt": artifact},
                evidence=["local probe only"],
            )
        receipt = self.ledger.finish(
            self.req["attempt"],
            1,
            "failed",
            exit_code=0,
            artifacts={"artifact.txt": artifact},
            reason="local probe is not approved model acceptance",
        )
        self.assertEqual(receipt["body"]["artifacts"]["artifact.txt"], artifact)

    def test_timeout_cleans_ordinary_process_group_and_env(self):
        script = "import subprocess,time,os; from pathlib import Path; p=subprocess.Popen(['/bin/sleep','30']); Path('child.pid').write_text(str(p.pid)); time.sleep(30)"
        result = run_bounded([sys.executable, "-c", script], self.root, 0.4)
        self.assertTrue(result["timed_out"])
        pid = (self.root / "child.pid").read_text()
        state = subprocess.run(
            ["/bin/ps", "-p", pid, "-o", "stat="],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()
        self.assertTrue(not state or state.startswith("Z"), state)
        result = run_bounded(
            [sys.executable, "-c", "import os; print(sorted(os.environ))"], self.root
        )
        self.assertNotIn("PAPERCLIP_API_KEY", result["stdout"])
        self.assertNotIn("OPENAI_API_KEY", result["stdout"])

    def test_kill_running_after_artifact_before_receipt(self):
        raw = canonical(self.req).decode()
        script = (
            "import os,signal; from pathlib import Path; from executor import Ledger,decode; "
            f"l=Ledger({str(self.path)!r},{RECEIPT!r}); r=decode({raw!r}); l.admit(r); "
            'l.start(r["attempt"],r["fence"]); '
            f'Path({str(self.root / "interrupted.txt")!r}).write_text("real interrupted artifact"); '
            "os.kill(os.getpid(),signal.SIGKILL)"
        )
        child = subprocess.run(
            [sys.executable, "-c", script], cwd=Path(__file__).parent, check=False
        )
        self.assertEqual(child.returncode, -signal.SIGKILL)
        self.assertTrue((self.root / "interrupted.txt").exists())
        pending = self.ledger.lookup(self.req["attempt"], COMPANY, PROJECT)
        self.assertEqual(pending["state"], "running")
        receipt = self.ledger.reconcile(self.req["attempt"], 1)
        self.assertEqual(receipt["body"]["state"], "unknown")
        self.assertEqual(receipt["body"]["artifacts"], {})
        with self.assertRaises(Denied):
            validate_success(receipt, self.req, RECEIPT)

    def test_client_real_subprocess_and_lost_reply(self):
        keys = self.root / "keys.json"
        keys.write_text(
            json.dumps({"controller_public": PUBLIC.hex(), "receipt": RECEIPT.hex()})
        )
        keys.chmod(0o600)
        config = self.root / "config.json"
        config.write_text(
            json.dumps(
                {
                    "keys_file": str(keys),
                    "database": str(self.path),
                    "company": COMPANY,
                    "project": PROJECT,
                    "repo": self.req["repo"],
                    "base_commit": BASE,
                }
            )
        )
        config.chmod(0o600)
        data = canonical(
            {"operation": "submit", "request": self.req, "grant": self.grant()}
        ).decode()
        cmd = [sys.executable, str(Path(__file__).parent / "client.py"), str(config)]
        first = subprocess.run(
            cmd, input=data, capture_output=True, text=True, check=False
        )
        second = subprocess.run(
            cmd, input=data, capture_output=True, text=True, check=False
        )
        self.assertEqual(first.returncode, 2)
        self.assertEqual(second.returncode, 2)
        self.assertEqual(decode(first.stdout), decode(second.stdout))
        self.assertEqual(decode(first.stdout)["body"]["state"], "failed")
        self.assertEqual(
            self.ledger.db.execute("SELECT count(*) FROM attempts").fetchone()[0], 1
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
