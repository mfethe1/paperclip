"""SQLite sidecar lifecycle/security regressions for the executor ledger.

Root cause (owner reproduction with a real WAL-churn diagnose loop): SQLite
last close may unlink -wal/-shm between the directory lookup and the metadata
snapshot; the original open+fstat validation then observed a zero-link
regular file and denied a healthy ledger (about 1 in 50 opens). The fix
validates one no-follow snapshot and rechecks the name only for a vanished
zero-link entry; every surviving or replaced entry must pass all original
regular/owner/mode/single-link rules. All fixtures here are real filesystem
objects; the zero-link snapshot is a real fstat of an unlinked open file.
"""

import os
import tempfile
import unittest
from pathlib import Path

from executor_fixtures import RECEIPT
from executor_ledger import Ledger
from security import (
    Denied,
    check_file_stat,
    check_sidecar,
    stat_entry,
    validate_sidecar,
)


def tripwire():
    raise AssertionError("recheck must not run for this snapshot")


class SidecarCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(
            dir=Path.home() / ".hermes/cache/scratch"
        )
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def make_file(self, name, mode=0o600, data=b"x"):
        path = self.root / name
        path.write_bytes(data)
        path.chmod(mode)
        return path

    def vanished_snapshot(self):
        # Real zero-link metadata: fstat of a still-open unlinked file.
        path = self.make_file("vanished")
        fd = os.open(path, os.O_RDONLY)
        try:
            path.unlink()
            info = os.fstat(fd)
        finally:
            os.close(fd)
        self.assertEqual(info.st_nlink, 0)
        self.assertFalse(path.exists())
        return info

    def lookup(self, path):
        def real_lookup():
            try:
                return os.stat(path, follow_symlinks=False)
            except FileNotFoundError:
                return None

        return real_lookup

    def vanished_snapshot2(self):
        path = self.make_file("vanished2")
        fd = os.open(path, os.O_RDONLY)
        try:
            path.unlink()
            info = os.fstat(fd)
        finally:
            os.close(fd)
        self.assertEqual(info.st_nlink, 0)
        return info


class SidecarValidationTests(SidecarCase):
    def test_absent_name_is_skipped_without_recheck(self):
        self.assertIsNone(validate_sidecar(None, tripwire))

    def test_valid_entry_passes_without_recheck(self):
        path = self.make_file("ok")
        validate_sidecar(os.stat(path), tripwire)

    def test_removed_file_causes_no_false_denial(self):
        first = self.vanished_snapshot()
        gone = self.root / "vanished"
        # The name is really gone; skipping it must not deny the ledger.
        self.assertIsNone(validate_sidecar(first, self.lookup(gone)))

    def test_surviving_valid_replacement_passes(self):
        first = self.vanished_snapshot()
        replacement = self.make_file("replacement")
        validate_sidecar(first, self.lookup(replacement))

    def test_replacement_must_pass_all_original_checks(self):
        builds = (
            ("mode", lambda n: self.make_file(n, mode=0o644)),
            ("hardlink", self._hardlinked),
            ("symlink", self._symlink),
            ("directory", self._directory),
            ("fifo", self._fifo),
        )
        for label, build in builds:
            with self.subTest(case=label):
                first = self.vanished_snapshot()
                target = build(f"bad-{label}")
                with self.assertRaises(Denied):
                    validate_sidecar(first, self.lookup(target))

    def test_persistent_zero_link_churn_fails_closed(self):
        first = self.vanished_snapshot()
        with self.assertRaises(Denied):
            validate_sidecar(first, self.vanished_snapshot2)

    def test_nonzero_violations_are_final_without_recheck(self):
        for snapshot in (
            os.stat(self.make_file("group", mode=0o640)),
            os.stat(self._hardlinked("linked")),
            os.stat(self._symlink("link"), follow_symlinks=False),
            os.stat(self._directory("dir")),
            os.stat(self._fifo("pipe"), follow_symlinks=False),
        ):
            with self.subTest(snapshot=snapshot), self.assertRaises(Denied):
                validate_sidecar(snapshot, tripwire)

    def test_check_file_stat_hostile_baseline_unchanged(self):
        with self.assertRaises(Denied):
            check_file_stat(self.vanished_snapshot(), bounded=False)
        with self.assertRaises(Denied):
            check_file_stat(os.stat(self.make_file("w", mode=0o644)), bounded=False)
        with self.assertRaises(Denied):
            check_file_stat(os.stat(self._hardlinked("h")), bounded=False)
        with self.assertRaises(Denied):
            check_file_stat(
                os.stat(self._symlink("s"), follow_symlinks=False), bounded=False
            )
        info = check_file_stat(os.stat(self.make_file("fine")), bounded=False)
        self.assertEqual(info.st_nlink, 1)

    def test_check_sidecar_real_parent_fd(self):
        parent = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            check_sidecar(parent, "absent-wal")
            self.make_file("real-wal", mode=0o644)
            with self.assertRaises(Denied):
                check_sidecar(parent, "real-wal")
            (self.root / "real-wal").chmod(0o600)
            check_sidecar(parent, "real-wal")
            self.assertIsNone(stat_entry(parent, "absent-shm"))
        finally:
            os.close(parent)

    def _hardlinked(self, name):
        original = self.make_file(name + "-original")
        linked = self.root / name
        os.link(original, linked)
        return linked

    def _symlink(self, name):
        target = self.make_file(name + "-target")
        link = self.root / name
        link.symlink_to(target)
        return link

    def _directory(self, name):
        path = self.root / name
        path.mkdir()
        return path

    def _fifo(self, name):
        path = self.root / name
        os.mkfifo(path)
        return path


class LedgerSidecarTests(SidecarCase):
    def setUp(self):
        super().setUp()
        self.path = self.root / "ledger.sqlite"
        Ledger(self.path, RECEIPT).close()

    def denied_with(self, name, build):
        build(self.root / name)
        try:
            with self.assertRaises(Denied):
                Ledger(self.path, RECEIPT)
        finally:
            entry = self.root / name
            if entry.is_dir() and not entry.is_symlink():
                entry.rmdir()
            elif entry.exists() or entry.is_symlink():
                entry.unlink()

    def test_sidecar_suffixes_enforced_end_to_end(self):
        for suffix in ("-wal", "-shm", "-journal"):
            name = self.path.name + suffix
            with self.subTest(name=name, case="mode"):
                self.denied_with(name, lambda p: (p.write_bytes(b"x"), p.chmod(0o644)))
            with self.subTest(name=name, case="symlink"):
                target = self.make_file("target-" + suffix[1:])
                self.denied_with(name, lambda p, bound=target: p.symlink_to(bound))
            with self.subTest(name=name, case="directory"):
                self.denied_with(name, lambda p: p.mkdir())

    def test_hardlinked_sidecar_denied_end_to_end(self):
        original = self.make_file("shared")
        self.denied_with(self.path.name + "-wal", lambda p: os.link(original, p))

    def test_valid_sidecars_do_not_block_open(self):
        for suffix in ("-wal", "-shm", "-journal"):
            side = self.root / (self.path.name + suffix)
            side.write_bytes(b"")
            side.chmod(0o600)
        Ledger(self.path, RECEIPT).close()

    def test_repeated_open_close_no_false_denial(self):
        # Regression repro: the pre-fix open+fstat sidecar validation denied a
        # healthy ledger about 1/50 opens under WAL last-close unlink churn.
        for _ in range(50):
            Ledger(self.path, RECEIPT).close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
