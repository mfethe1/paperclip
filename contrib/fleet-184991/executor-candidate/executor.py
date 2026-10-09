"""Private candidate: authenticated admission and receipts; execution stays closed.

Controller assembly of the executor prototype: binds the pure protocol
(executor_protocol.py) and the durable ledger (executor_ledger.py) to the
closed backend and the fixed process-adapter entrypoint. Protocol and ledger
are independently testable; this module only wires them together.
"""

import hmac
import os
import re
import sqlite3
import sys
import time
import uuid

from executor_ledger import Ledger
from executor_protocol import (
    BLOCKER,
    FIELDS,
    MODEL,
    POLICY,
    PROVIDER,
    TERMINAL,
    TERMINAL_FIELDS,
    Contract,
    canonical,
    check_signature,
    decode,
    digest,
    tag,
    validate_success,
    validate_terminal,
)
from security import (
    Denied,
    check_file,
    finite_number,
    protected_parent,
    read_frame,
    read_private_fd,
    verify_public,
)

__all__ = [
    "BLOCKER",
    "FIELDS",
    "MODEL",
    "POLICY",
    "PROVIDER",
    "TERMINAL",
    "TERMINAL_FIELDS",
    "Contract",
    "Controller",
    "Denied",
    "DisabledBackend",
    "Ledger",
    "canonical",
    "check_signature",
    "decode",
    "digest",
    "main",
    "private_json",
    "tag",
    "validate_success",
    "validate_terminal",
]


class DisabledBackend:
    def launch(self, request):
        raise Denied(BLOCKER)


class Controller:
    def __init__(self, ledger, contract, controller_key):
        self.ledger, self.contract, self.controller_key = (
            ledger,
            contract,
            controller_key,
        )
        if hmac.compare_digest(ledger.key, controller_key):
            raise Denied("controller and receipt authorities must be separate")
        self.backend = DisabledBackend()

    def _grant(self, grant, expected_digest, domain, now):
        if type(grant) is not dict or set(grant) != {"body", "signature"}:
            raise Denied("missing controller authorization")
        body = grant["body"]
        if (
            type(body) is not dict
            or set(body) != {"request_digest", "expires", "issuer"}
            or not finite_number(body["expires"])
            or not now < body["expires"] <= now + 600
            or body["issuer"] != "paperclip-controller"
            or body["request_digest"] != expected_digest
        ):
            raise Denied("invalid/expired controller grant")
        verify_public(self.controller_key, domain, canonical(body), grant["signature"])
        return body

    def status(self, query, grant):
        if type(query) is not dict or set(query) != {
            "company",
            "project",
            "attempt",
            "request_digest",
        }:
            raise Denied("invalid status query")
        for field in ("company", "project", "attempt"):
            value = query[field]
            if type(value) is not str:
                raise Denied("invalid status identifier")
            try:
                if str(uuid.UUID(value)) != value or uuid.UUID(value).int == 0:
                    raise Denied("invalid status identifier")
            except ValueError as error:
                raise Denied("invalid status identifier") from error
        if (
            query["company"] != self.contract.company
            or query["project"] != self.contract.project
            or type(query["request_digest"]) is not str
            or not re.fullmatch(r"[0-9a-f]{64}", query["request_digest"])
        ):
            raise Denied("status tenant/identity mismatch")
        self._grant(grant, digest(query), "status-v2", time.time())
        row = self.ledger.db.execute(
            "SELECT digest FROM attempts WHERE attempt=? AND company=? AND project=?",
            (query["attempt"], query["company"], query["project"]),
        ).fetchone()
        if row is None or row["digest"] != query["request_digest"]:
            raise Denied("unknown status identity")
        return self.ledger.lookup(query["attempt"], query["company"], query["project"])

    def submit(self, request, grant):
        now = time.time()
        self.contract.validate(request, now)
        body = self._grant(grant, digest(request), "submit-v2", now)
        if body["expires"] > request["deadline"]:
            raise Denied("grant outlives submission")
        attempt, created = self.ledger.admit(request)
        if not created:
            return self.ledger.lookup(attempt, request["company"], request["project"])
        try:
            self.backend.launch(request)
        except Denied as error:
            return self.ledger.finish(
                attempt, request["fence"], "failed", reason=str(error)
            )
        raise Denied("unqualified backend returned")


def private_json(path):
    parent, name = protected_parent(path)
    fd = None
    try:
        fd = os.open(
            name,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
            dir_fd=parent,
        )
        check_file(fd)
        raw = read_private_fd(fd)
        return decode(raw)
    finally:
        if fd is not None:
            os.close(fd)
        os.close(parent)


def main():
    # Fixed process-adapter command: python3 <absolute>/client.py <host-config>.
    # No model launch, shell interpolation, network ingress or nested delegation.
    if len(sys.argv) != 2:
        raise Denied("expected host configuration path")
    config = private_json(sys.argv[1])
    if type(config) is not dict or set(config) != {
        "company",
        "project",
        "repo",
        "base_commit",
        "database",
        "keys_file",
    }:
        raise Denied("host config schema mismatch")
    keys = private_json(config["keys_file"])
    if type(keys) is not dict or set(keys) != {"controller_public", "receipt"}:
        raise Denied("public controller/receipt key schema mismatch")
    if any(
        type(value) is not str or not re.fullmatch(r"[0-9a-f]{64}", value)
        for value in keys.values()
    ):
        raise Denied("exact canonical 32-byte key encoding required")
    controller_public, receipt_key = (
        bytes.fromhex(keys["controller_public"]),
        bytes.fromhex(keys["receipt"]),
    )
    if controller_public == receipt_key:
        raise Denied("key separation required")
    data = decode(read_frame(sys.stdin.fileno()))
    if type(data) is not dict or data.get("operation") not in ("submit", "status"):
        raise Denied("explicit operation required")
    status = data["operation"] == "status"
    if set(data) != {"operation", "query" if status else "request", "grant"}:
        raise Denied("invalid envelope")
    ledger = Ledger(config["database"], receipt_key, readonly=status)
    try:
        contract = Contract(
            config["company"], config["project"], config["repo"], config["base_commit"]
        )
        controller = Controller(ledger, contract, controller_public)
        envelope = (
            controller.status(data["query"], data["grant"])
            if status
            else controller.submit(data["request"], data["grant"])
        )
        print(canonical(envelope).decode())
        if not status:
            validate_success(envelope, data["request"], receipt_key)
        return 0  # status transport success is NOT task success
    finally:
        ledger.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (Denied, KeyError, TypeError, OSError, sqlite3.Error, ValueError) as error:
        print(
            canonical({"error": str(error), "execution_enabled": False}).decode(),
            file=sys.stderr,
        )
        raise SystemExit(2)
