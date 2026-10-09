"""Review a3bb8cd F2/F3 storage regressions: schema, identity, host files."""

import hashlib
import os
import sqlite3
import sys
import unittest
from pathlib import Path

import executor_fixtures as fixtures
from executor import (
    Denied,
    Ledger,
    private_json,
)
from executor_fixtures import RECEIPT


class StorageRegressions(fixtures.CandidateCase):
    def test_F2_wrong_named_index_rejected_unchanged(self):
        self.ledger.close()
        db = sqlite3.connect(self.path)
        db.executescript(
            "DROP INDEX one_reservation; CREATE UNIQUE INDEX one_reservation ON attempts(attempt);"
        )
        db.close()
        before = hashlib.sha256(self.path.read_bytes()).hexdigest()
        with self.assertRaises(Denied):
            other = Ledger(self.path, RECEIPT)
            other.close()
        self.assertEqual(before, hashlib.sha256(self.path.read_bytes()).hexdigest())

    def test_F2_foreign_db_rejected_unchanged(self):
        path = self.root / "foreign.sqlite"
        db = sqlite3.connect(path)
        db.execute("CREATE TABLE unrelated(value)")
        db.close()
        path.chmod(0o600)
        before = path.read_bytes()
        with self.assertRaises(Denied):
            other = Ledger(path, RECEIPT)
            other.close()
        self.assertEqual(before, path.read_bytes())

    def test_F2_wrong_trigger_and_incomplete_init_rejected(self):
        for sql in (
            "DROP TRIGGER receipt_no_update; CREATE TRIGGER receipt_no_update BEFORE UPDATE ON receipts BEGIN SELECT 1; END;",
            "PRAGMA user_version=0;",
        ):
            with self.subTest(sql=sql):
                self.ledger.close()
                db = sqlite3.connect(self.path)
                db.executescript(sql)
                db.close()
                before = self.path.read_bytes()
                with self.assertRaises(Denied):
                    Ledger(self.path, RECEIPT)
                self.assertEqual(before, self.path.read_bytes())
                # Restore exact baseline only inside this disposable test directory.
                self.path.unlink()
                self.ledger = Ledger(self.path, RECEIPT)

    def test_F3_same_fd_json_despite_path_replacement(self):
        path, target = self.root / "config.json", self.root / "unchecked.json"
        path.write_text('{"source":"CHECKED"}')
        path.chmod(0o600)
        target.write_text('{"source":"UNCHECKED"}')
        target.chmod(0o644)
        changed = False

        def trace(frame, event, arg):
            nonlocal changed
            if (
                event == "line"
                and frame.f_code.co_name == "private_json"
                and not changed
            ):
                # Wait until an actual fd has been opened in the fixed code; the old
                # code's final read_text line reproduces the review scheduling proof.
                line = (
                    Path(frame.f_code.co_filename)
                    .read_text()
                    .splitlines()[frame.f_lineno - 1]
                )
                if "path.read_text()" in line or "read_private_fd(" in line:
                    path.unlink()
                    path.symlink_to(target)
                    changed = True
            return trace

        sys.settrace(trace)
        try:
            try:
                value = private_json(path)
            except Denied:
                value = (
                    None  # unlink invalidates single-link requirement, safely closed
                )
        finally:
            sys.settrace(None)
        self.assertIn(value, (None, {"source": "CHECKED"}))
        self.assertTrue(changed)

    def test_F3_ledger_reopen_race_rejects_target_unchanged(self):
        self.ledger.close()
        target = self.root / "protected_fixture"
        db = sqlite3.connect(target)
        db.execute("CREATE TABLE unrelated(value)")
        db.close()
        target.chmod(0o600)
        before = target.read_bytes()
        changed = False

        def trace(frame, event, arg):
            nonlocal changed
            if event == "line" and frame.f_code.co_name == "__init__" and not changed:
                line = (
                    Path(frame.f_code.co_filename)
                    .read_text()
                    .splitlines()[frame.f_lineno - 1]
                )
                if "inspect = sqlite3.connect(" in line:
                    self.path.unlink()
                    self.path.symlink_to(target)
                    changed = True
            return trace

        sys.settrace(trace)
        try:
            with self.assertRaises((Denied, OSError)):
                Ledger(self.path, RECEIPT)
        finally:
            sys.settrace(None)
        self.assertTrue(changed)
        self.assertEqual(before, target.read_bytes())

    def test_F3_private_file_type_links_size_and_ancestors(self):

        path = self.root / "input"
        for kind in ("fifo", "directory", "oversize", "hardlink"):
            with self.subTest(kind=kind):
                if kind == "fifo":
                    os.mkfifo(path, 0o600)
                elif kind == "directory":
                    path.mkdir(mode=0o700)
                else:
                    path.write_bytes(b"x" * (65537 if kind == "oversize" else 1))
                    path.chmod(0o600)
                    if kind == "hardlink":
                        os.link(path, self.root / "alias")
                with self.assertRaises(Denied):
                    private_json(path)
                path.rmdir() if path.is_dir() else path.unlink()
        linked = self.root / "linked"
        linked.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(OSError):
            private_json(linked / "config")
        unsafe = self.root / "unsafe"
        unsafe.mkdir()
        unsafe.chmod(0o777)
        with self.assertRaises(Denied):
            private_json(unsafe / "config")


if __name__ == "__main__":
    unittest.main(verbosity=2)
