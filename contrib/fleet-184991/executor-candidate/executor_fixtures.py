"""Shared real fixtures for the executor candidate suites (sanitized IDs only)."""

import sqlite3
import tempfile
import time
import unittest
import uuid
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from executor import (
    MODEL,
    POLICY,
    PROVIDER,
    Contract,
    Controller,
    Denied,
    Ledger,
    canonical,
    digest,
)

COMPANY = "00000000-0000-4000-8000-0000000000c0"  # sanitized: synthetic fixture, not a real instance ID
PROJECT = "00000000-0000-4000-8000-0000000000e0"  # sanitized: synthetic fixture, not a real instance ID
BASE = "a" * 40

KEY = Ed25519PrivateKey.generate()  # TEST ONLY, never enrolled
PUBLIC = KEY.public_key().public_bytes_raw()
RECEIPT = b"r" * 32


def authorize(req, key, expires):
    body = {
        "request_digest": digest(req),
        "expires": expires,
        "issuer": "paperclip-controller",
    }
    return {
        "body": body,
        "signature": key.sign(b"submit-v2\x00" + canonical(body)).hex(),
    }

def authorize_status(query, key, expires):
    body = {
        "request_digest": digest(query),
        "expires": expires,
        "issuer": "paperclip-controller",
    }
    return {
        "body": body,
        "signature": key.sign(b"status-v2\x00" + canonical(body)).hex(),
    }

def request():
    return {
        "company": COMPANY,
        "project": PROJECT,
        "issue": str(uuid.uuid4()),
        "run": str(uuid.uuid4()),
        "origin_thread": "184991",
        "approval_scope": "local-artifact-only",
        "repo": "/private/test-repository",
        "base_commit": BASE,
        "policy": POLICY,
        "attempt": str(uuid.uuid4()),
        "fence": 1,
        "deadline": time.time() + 120,
        "idempotency_key": uuid.uuid4().hex,
        "model": MODEL,
        "provider": PROVIDER,
        "lineage": {"source": "paperclip-controller", "role": "controller", "depth": 0},
        "task": "Produce one local artifact; never delegate.",
    }

def race(path, req, gate, queue):
    ledger = None
    try:
        ledger = Ledger(path, RECEIPT)
        gate.wait(5)
        result = ("ok", ledger.admit(req))
    except (Denied, sqlite3.Error) as error:
        result = ("denied", str(error))
    finally:
        if ledger is not None:
            ledger.close()
    queue.put(result)
    queue.close()
    queue.join_thread()


class CandidateCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(
            dir=Path.home() / ".hermes/cache/scratch"
        )
        self.root = Path(self.tmp.name)
        self.path = self.root / "ledger.sqlite"
        self.ledger = Ledger(self.path, RECEIPT)
        self.req = request()
        self.contract = Contract(COMPANY, PROJECT, self.req["repo"], BASE)
        self.controller = Controller(self.ledger, self.contract, PUBLIC)

    def tearDown(self):
        self.ledger.close()
        self.tmp.cleanup()

    def grant(self, req=None):
        req = req or self.req
        return authorize(req, KEY, req["deadline"])

    def status_grant(self, query):
        return authorize_status(query, KEY, time.time() + 30)

    def success_body(self):
        now = time.time()
        return {
            **{
                k: self.req[k]
                for k in (
                    "attempt",
                    "company",
                    "project",
                    "issue",
                    "run",
                    "origin_thread",
                    "fence",
                    "policy",
                )
            },
            "version": 1,
            "request_digest": digest(self.req),
            "state": "succeeded",
            "accepted": now - 1,
            "started": now - 0.5,
            "finished": now,
            "exit_code": 0,
            "actual_model": MODEL,
            "actual_provider": PROVIDER,
            "artifacts": {"fixture.txt": "c" * 64},
            "evidence": [
                {
                    "kind": "task-verification",
                    "passed": True,
                    "request_digest": digest(self.req),
                    "scope": "UNIT ONLY",
                }
            ],
            "reason": "",
        }
