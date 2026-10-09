"""Durable ledger tests: idempotency, fencing, races, immutable receipts."""

import multiprocessing
import signal
import sqlite3
import subprocess
import sys
import unittest
import uuid
from pathlib import Path

import executor_fixtures as fixtures
from executor import (
    Denied,
    Ledger,
    canonical,
)
from executor_fixtures import COMPANY, PROJECT, RECEIPT, race


class LedgerTests(fixtures.CandidateCase):
    def test_duplicate_terminal_and_restart(self):
        first = self.controller.submit(self.req, self.grant())
        self.assertEqual(first, self.controller.submit(self.req, self.grant()))
        self.ledger.close()
        self.ledger = Ledger(self.path, RECEIPT)
        self.assertEqual(
            first, self.ledger.lookup(self.req["attempt"], COMPANY, PROJECT)
        )

    def test_stale_fence_and_active_attempt(self):
        self.ledger.admit(self.req)
        changed = dict(
            self.req,
            attempt=str(uuid.uuid4()),
            idempotency_key=uuid.uuid4().hex,
            fence=2,
        )
        with self.assertRaises(Denied):
            self.ledger.admit(changed)
        self.ledger.finish(self.req["attempt"], 1, "failed", reason="not launched")
        stale = dict(changed, fence=1)
        with self.assertRaisesRegex(Denied, "stale fence"):
            self.ledger.admit(stale)
        self.assertTrue(self.ledger.admit(changed)[1])
        with self.assertRaises(Denied):
            self.ledger.start(changed["attempt"], 1)

    def test_separate_process_duplicate_transaction(self):
        ctx = multiprocessing.get_context("spawn")
        gate, queue = ctx.Event(), ctx.Queue()
        children = [
            ctx.Process(target=race, args=(str(self.path), self.req, gate, queue))
            for _ in range(5)
        ]
        for child in children:
            child.start()
        gate.set()
        results = [queue.get(timeout=10) for _ in children]
        for child in children:
            child.join(10)
            self.assertEqual(child.exitcode, 0)
        self.assertTrue(all(kind == "ok" for kind, _ in results), results)
        self.assertEqual(sum(result[1] for _, result in results), 1)
        self.assertEqual(
            self.ledger.db.execute("SELECT count(*) FROM attempts").fetchone()[0], 1
        )

    def test_separate_process_competing_attempts(self):
        ctx = multiprocessing.get_context("spawn")
        gate, queue = ctx.Event(), ctx.Queue()
        requests = [
            dict(self.req, attempt=str(uuid.uuid4()), idempotency_key=uuid.uuid4().hex)
            for _ in range(4)
        ]
        children = [
            ctx.Process(target=race, args=(str(self.path), r, gate, queue))
            for r in requests
        ]
        for child in children:
            child.start()
        gate.set()
        results = [queue.get(timeout=10) for _ in children]
        for child in children:
            child.join(10)
            self.assertEqual(child.exitcode, 0)
        self.assertEqual(sum(kind == "ok" for kind, _ in results), 1, results)

    def test_killed_after_admission_reconcile_retains_reservation(self):
        raw = canonical(self.req).decode()
        script = (
            "import os,signal; from executor import Ledger,decode; "
            f"l=Ledger({str(self.path)!r},{RECEIPT!r}); l.admit(decode({raw!r})); "
            "os.kill(os.getpid(),signal.SIGKILL)"
        )
        child = subprocess.run(
            [sys.executable, "-c", script], cwd=Path(__file__).parent, check=False
        )
        self.assertEqual(child.returncode, -signal.SIGKILL)
        result = self.ledger.reconcile(self.req["attempt"], 1)
        self.assertEqual(result["body"]["state"], "unknown")
        changed = dict(
            self.req,
            attempt=str(uuid.uuid4()),
            idempotency_key=uuid.uuid4().hex,
            fence=2,
        )
        with self.assertRaises(Denied):
            self.ledger.admit(changed)
        with self.assertRaises(Denied):
            self.ledger.lookup(self.req["attempt"], str(uuid.uuid4()), PROJECT)
        with self.assertRaises(Denied):
            self.ledger.lookup(str(uuid.uuid4()), COMPANY, PROJECT)

    def test_immutable_receipt_and_terminal(self):
        self.controller.submit(self.req, self.grant())
        for sql in [
            'UPDATE receipts SET signature="bad"',
            "DELETE FROM receipts",
            'UPDATE attempts SET state="accepted"',
        ]:
            with self.assertRaises(sqlite3.IntegrityError):
                self.ledger.db.execute(sql)
        with self.assertRaises(Denied):
            self.ledger.finish(self.req["attempt"], 1, "succeeded", exit_code=0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
