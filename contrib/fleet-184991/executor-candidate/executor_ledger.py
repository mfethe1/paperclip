"""Private candidate: authenticated admission and receipts; execution stays closed.

Durable half of the executor prototype: the fail-closed SQLite ledger with
schema validation, fencing, idempotent admission, immutable receipts and
sidecar identity validation. Depends only on security.py host-IO primitives
and executor_protocol.py pure protocol; the controller assembly is executor.py.
"""

import os
import sqlite3
import time
from urllib.parse import quote

from executor_protocol import (
    POLICY,
    TERMINAL,
    canonical,
    check_signature,
    decode,
    digest,
    tag,
    validate_terminal,
)
from security import Denied, check_file, check_sidecar, protected_parent

# No controller private-key signing primitive exists in production source.
SCHEMA = """
        CREATE TABLE fences(company TEXT, project TEXT, issue TEXT, fence INTEGER,
          PRIMARY KEY(company,project,issue));
        CREATE TABLE attempts(
          attempt TEXT PRIMARY KEY, company TEXT NOT NULL, project TEXT NOT NULL,
          issue TEXT NOT NULL, idem TEXT NOT NULL, digest TEXT NOT NULL, request TEXT NOT NULL,
          fence INTEGER NOT NULL, state TEXT NOT NULL CHECK(state IN
            ('accepted','running','succeeded','failed','cancelled','unknown')),
          accepted REAL NOT NULL, started REAL,
          UNIQUE(company,project,idem));
        CREATE UNIQUE INDEX one_reservation ON attempts(company,project,issue)
          WHERE state IN ('accepted','running','unknown');
        CREATE TABLE receipts(attempt TEXT PRIMARY KEY REFERENCES attempts(attempt),
          body TEXT NOT NULL, signature TEXT NOT NULL);
        CREATE TRIGGER receipt_no_update BEFORE UPDATE ON receipts
          BEGIN SELECT RAISE(ABORT,'immutable receipt'); END;
        CREATE TRIGGER receipt_no_delete BEFORE DELETE ON receipts
          BEGIN SELECT RAISE(ABORT,'immutable receipt'); END;
        CREATE TRIGGER terminal_no_update BEFORE UPDATE ON attempts
          WHEN OLD.state IN ('succeeded','failed','cancelled','unknown')
          BEGIN SELECT RAISE(ABORT,'immutable terminal attempt'); END;
        CREATE TRIGGER attempt_identity BEFORE UPDATE ON attempts
          WHEN NEW.attempt != OLD.attempt OR NEW.company != OLD.company OR
            NEW.project != OLD.project OR NEW.issue != OLD.issue OR NEW.idem != OLD.idem OR
            NEW.digest != OLD.digest OR NEW.request != OLD.request OR NEW.fence != OLD.fence OR
            NEW.accepted != OLD.accepted
          BEGIN SELECT RAISE(ABORT,'immutable identity'); END;
"""
APPLICATION_ID = 0x50434558
SCHEMA_VERSION = 2


def schema_rows(db):
    return sorted(
        tuple(row)
        for row in db.execute("SELECT type,name,tbl_name,sql FROM sqlite_master")
    )


def validate_schema(db):
    expected = sqlite3.connect(":memory:")
    try:
        expected.executescript(SCHEMA)
        if (
            db.execute("PRAGMA application_id").fetchone()[0] != APPLICATION_ID
            or db.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION
            or schema_rows(db) != schema_rows(expected)
            or db.execute("PRAGMA quick_check").fetchall() != [("ok",)]
            or db.execute("PRAGMA foreign_key_check").fetchall()
        ):
            raise Denied("unrecognized or corrupt ledger schema")
    finally:
        expected.close()


class Ledger:
    def __init__(self, path, receipt_key, *, readonly=False):
        self.path = str(path)
        self.key = receipt_key
        self.readonly = readonly
        self.db = None
        self.parent_fd, name = protected_parent(path, private=True)
        self.file_fd = None
        created = False
        try:
            flags = os.O_RDONLY if readonly else os.O_RDWR
            flags |= os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
            try:
                self.file_fd = os.open(name, flags, dir_fd=self.parent_fd)
            except FileNotFoundError:
                if readonly:
                    raise Denied("status ledger does not exist") from None
                self.file_fd = os.open(
                    name, flags | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=self.parent_fd
                )
                created = True
            original = check_file(self.file_fd, bounded=False)
            self._check_identity(original)
            # Existing ledgers are inspected with immutable read-only SQLite BEFORE
            # any persistent pragma or schema write. Active WAL is validated again
            # by the actual connection; checkpointed main schema is authoritative.
            if not created:
                inspect = sqlite3.connect(
                    "file:" + quote(self.path) + "?mode=ro&immutable=1", uri=True
                )
                try:
                    self._check_identity(original)
                    validate_schema(inspect)
                finally:
                    inspect.close()
            self.db = sqlite3.connect(
                "file:" + quote(self.path) + ("?mode=ro" if readonly else "?mode=rw"),
                uri=True,
                timeout=10,
                isolation_level=None,
            )
            self._check_identity(original)
            if created:
                self.db.executescript(
                    "BEGIN IMMEDIATE;\n"
                    + SCHEMA
                    + f"PRAGMA application_id={APPLICATION_ID}; PRAGMA user_version={SCHEMA_VERSION}; COMMIT;"
                )
                # Persist schema in main DB before enabling WAL.
            validate_schema(self.db)
            self.db.row_factory = sqlite3.Row
            if not readonly:
                self.db.execute("PRAGMA journal_mode=WAL")
                self.db.execute("PRAGMA synchronous=FULL")
            self.db.execute("PRAGMA foreign_keys=ON")
            self.db.execute("PRAGMA trusted_schema=OFF")
            self._check_identity(original)
        except BaseException:
            self.close()
            raise

    def _check_identity(self, original):
        parent, name = protected_parent(self.path, private=True)
        try:
            if (os.fstat(parent).st_dev, os.fstat(parent).st_ino) != (
                os.fstat(self.parent_fd).st_dev,
                os.fstat(self.parent_fd).st_ino,
            ):
                raise Denied("ledger directory changed")
            fd = os.open(
                name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent
            )
            try:
                current = check_file(fd, bounded=False)
                if (current.st_dev, current.st_ino) != (
                    original.st_dev,
                    original.st_ino,
                ):
                    raise Denied("ledger identity changed")
            finally:
                os.close(fd)
            for suffix in ("-wal", "-shm", "-journal"):
                # Last close may unlink a SQLite sidecar between directory
                # lookup and metadata capture. check_sidecar tolerates only a
                # vanished zero-link snapshot; any surviving or replaced entry
                # must pass every original regular/owner/mode/single-link rule.
                check_sidecar(parent, name + suffix)
        finally:
            os.close(parent)

    def close(self):
        if self.db is not None:
            self.db.close()
            self.db = None
        for name in ("file_fd", "parent_fd"):
            fd = getattr(self, name, None)
            if fd is not None:
                os.close(fd)
                setattr(self, name, None)

    def admit(self, request):
        identity = digest(request)
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self.db.execute(
                "SELECT * FROM attempts WHERE company=? AND project=? AND idem=?",
                (request["company"], request["project"], request["idempotency_key"]),
            ).fetchone()
            if row:
                if row["digest"] != identity:
                    raise Denied("idempotency conflict")
                self.db.execute("COMMIT")
                return row["attempt"], False
            old = self.db.execute(
                "SELECT fence FROM fences WHERE company=? AND project=? AND issue=?",
                (request["company"], request["project"], request["issue"]),
            ).fetchone()
            if old and request["fence"] <= old["fence"]:
                raise Denied("stale fence")
            self.db.execute(
                "INSERT INTO attempts VALUES(?,?,?,?,?,?,?,?,?,?,NULL)",
                (
                    request["attempt"],
                    request["company"],
                    request["project"],
                    request["issue"],
                    request["idempotency_key"],
                    identity,
                    canonical(request).decode(),
                    request["fence"],
                    "accepted",
                    time.time(),
                ),
            )
            self.db.execute(
                "INSERT INTO fences VALUES(?,?,?,?) ON CONFLICT(company,project,issue) "
                "DO UPDATE SET fence=excluded.fence",
                (
                    request["company"],
                    request["project"],
                    request["issue"],
                    request["fence"],
                ),
            )
            self.db.execute("COMMIT")
            return request["attempt"], True
        except (Denied, sqlite3.IntegrityError) as error:
            self.db.execute("ROLLBACK")
            raise Denied(str(error)) from error
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def lookup(self, attempt, company, project):
        row = self.db.execute(
            "SELECT * FROM attempts WHERE attempt=? AND company=? AND project=?",
            (attempt, company, project),
        ).fetchone()
        if not row:
            raise Denied("not recorded for this tenant")
        receipt = self.db.execute(
            "SELECT body,signature FROM receipts WHERE attempt=?", (attempt,)
        ).fetchone()
        if receipt:
            envelope = {
                "body": decode(receipt["body"]),
                "signature": receipt["signature"],
            }
            check_signature(
                self.key, "receipt-v1", envelope["body"], envelope["signature"]
            )
            validate_terminal(envelope["body"], decode(row["request"]))
            if (
                envelope["body"]["request_digest"] != row["digest"]
                or envelope["body"]["state"] != row["state"]
            ):
                raise Denied("corrupt ledger")
            return envelope
        return {
            "state": row["state"],
            "attempt": attempt,
            "request_digest": row["digest"],
        }

    def start(self, attempt, fence):
        changed = self.db.execute(
            "UPDATE attempts SET state='running',started=? WHERE attempt=? AND fence=? AND state='accepted'",
            (time.time(), attempt, fence),
        ).rowcount
        if changed != 1:
            raise Denied("start fence/state mismatch")

    def finish(
        self,
        attempt,
        fence,
        state,
        *,
        exit_code=None,
        artifacts=None,
        evidence=None,
        actual_model=None,
        actual_provider=None,
        reason="",
    ):
        if state not in TERMINAL:
            raise Denied("invalid terminal state")
        artifacts = {} if artifacts is None else artifacts
        evidence = [] if evidence is None else evidence
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self.db.execute(
                "SELECT * FROM attempts WHERE attempt=?", (attempt,)
            ).fetchone()
            if (
                not row
                or row["fence"] != fence
                or row["state"] not in {"accepted", "running"}
            ):
                raise Denied("finish fence/state mismatch")
            if state == "succeeded" and row["state"] != "running":
                raise Denied("success without execution")
            request = decode(row["request"])
            body = {
                "version": 1,
                "attempt": attempt,
                "company": row["company"],
                "project": row["project"],
                "issue": row["issue"],
                "run": request["run"],
                "origin_thread": request["origin_thread"],
                "fence": fence,
                "request_digest": row["digest"],
                "policy": POLICY,
                "state": state,
                "accepted": row["accepted"],
                "started": row["started"],
                "finished": time.time(),
                "exit_code": exit_code,
                "actual_model": actual_model,
                "actual_provider": actual_provider,
                "artifacts": artifacts,
                "evidence": evidence,
                "reason": reason,
            }
            validate_terminal(body, request)
            if row["state"] == "running" and state != "unknown":
                # No qualified supervisor stop/broker-revocation channel exists.
                # Never release a running reservation on a caller's assertion.
                body["state"] = state = "unknown"
                body["reason"] = (
                    "supervised boundary stop and provider revocation unproven; reservation retained"
                )
                validate_terminal(body, request)
            signature = tag(self.key, "receipt-v1", body)
            self.db.execute(
                "UPDATE attempts SET state=? WHERE attempt=?", (state, attempt)
            )
            self.db.execute(
                "INSERT INTO receipts VALUES(?,?,?)",
                (attempt, canonical(body).decode(), signature),
            )
            self.db.execute("COMMIT")
            return {"body": body, "signature": signature}
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def reconcile(self, attempt, fence):
        # Never replay or release a reservation after an interrupted spawn boundary.
        return self.finish(
            attempt,
            fence,
            "unknown",
            reason="interrupted; reservation retained; independent reconciliation required",
        )
