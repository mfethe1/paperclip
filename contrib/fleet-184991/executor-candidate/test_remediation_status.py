"""Review a3bb8cd F6/F7 status/client regressions: readonly status, pipe discipline."""

import copy
import json
import sqlite3
import subprocess
import sys
import time
import unittest
from pathlib import Path

import executor_fixtures as fixtures
from executor import (
    Denied,
    Ledger,
    decode,
    digest,
)
from executor_fixtures import COMPANY, PROJECT, PUBLIC, RECEIPT
from probe_runner import run_bounded


class StatusClientRegressions(fixtures.CandidateCase):
    def test_F6_fresh_status_after_expired_submit(self):
        self.req["deadline"] = time.time() + 0.1
        first = self.controller.submit(self.req, self.grant())
        time.sleep(0.15)
        self.assertTrue(
            hasattr(self.controller, "status"), "missing fresh authenticated status API"
        )
        query = {
            "company": COMPANY,
            "project": PROJECT,
            "attempt": self.req["attempt"],
            "request_digest": digest(self.req),
        }
        grant = self.status_grant(query)
        before = self.ledger.db.total_changes
        self.assertEqual(self.controller.status(query, grant), first)
        self.assertEqual(self.ledger.db.total_changes, before)

    def test_F6_status_readonly_rejects_cross_tenant_and_wrong_grant(self):
        first = self.controller.submit(self.req, self.grant())
        query = {
            "company": COMPANY,
            "project": PROJECT,
            "attempt": self.req["attempt"],
            "request_digest": digest(self.req),
        }
        readonly = Ledger(self.path, RECEIPT, readonly=True)
        try:
            controller = fixtures.Controller(readonly, self.contract, fixtures.PUBLIC)
            self.assertEqual(first, controller.status(query, self.status_grant(query)))
            with self.assertRaises(sqlite3.OperationalError):
                readonly.db.execute("DELETE FROM fences")
            with self.assertRaises(Denied):
                controller.status(query, self.grant())
            wrong = dict(query, request_digest="c" * 64)
            with self.assertRaises(Denied):
                controller.status(wrong, self.status_grant(wrong))
            wrong = dict(query, company=str(fixtures.uuid.uuid4()))
            with self.assertRaises(Denied):
                controller.status(wrong, self.status_grant(wrong))
            self.assertEqual(readonly.db.total_changes, 0)
        finally:
            readonly.close()

    def test_F7_unterminated_real_client_pipe_times_out(self):

        keys = self.root / "keys.json"
        keys.write_text(
            json.dumps({"controller_public": PUBLIC.hex(), "receipt": RECEIPT.hex()})
        )
        keys.chmod(0o600)
        config = self.root / "config.json"
        config.write_text(
            json.dumps(
                {
                    "company": COMPANY,
                    "project": PROJECT,
                    "repo": self.req["repo"],
                    "base_commit": self.req["base_commit"],
                    "database": str(self.path),
                    "keys_file": str(keys),
                }
            )
        )
        config.chmod(0o600)
        child = subprocess.Popen(
            [sys.executable, str(Path(__file__).parent / "client.py"), str(config)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            child.stdin.write(b"{")
            child.stdin.flush()
            self.assertEqual(child.wait(timeout=4), 2)
            self.assertEqual(child.stdout.read(), b"")
            self.assertIn(b'"error_type":"Denied"', child.stderr.read())
        finally:
            if child.poll() is None:
                child.kill()
                child.wait()
            for stream in (child.stdin, child.stdout, child.stderr):
                stream.close()

    def test_F7_diagnostic_output_capped_and_explicitly_unqualified(self):

        result = run_bounded(
            [sys.executable, "-c", "import os; os.write(1,b'x'*1048576)"], self.root
        )
        self.assertTrue(result["output_limit_exceeded"])
        self.assertTrue(result["truncated"])
        self.assertLessEqual(len(result["stdout"].encode()), 65536)
        self.assertFalse(result["boundary_stop_proven"])

    def test_F7_overflow_and_exact_lineage(self):
        with self.assertRaises(Denied):
            decode('{"value":1e999}')
        for depth in (False, 0.0):
            changed = copy.deepcopy(self.req)
            changed["lineage"]["depth"] = depth
            with self.assertRaises(Denied):
                self.contract.validate(changed, time.time())


if __name__ == "__main__":
    unittest.main(verbosity=2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
