"""Direct executor_protocol unit tests: encoding, tags, contract, receipts.

No database or subprocess needed for the pure protocol half; the moved
success-validation fixture proves validate_success stays a unit check, never
fleet acceptance.
"""

import time
import unittest
import uuid

import executor_fixtures as fixtures
from executor_fixtures import BASE, COMPANY, PROJECT, RECEIPT
from executor_protocol import (
    MODEL,
    PROVIDER,
    Contract,
    Denied,
    canonical,
    check_signature,
    decode,
    digest,
    tag,
    validate_success,
    validate_terminal,
)


class ProtocolUnitTests(unittest.TestCase):
    def setUp(self):
        self.req = fixtures.request()
        self.contract = Contract(COMPANY, PROJECT, self.req["repo"], BASE)

    def test_decode_rejects_duplicate_nonfinite_and_oversize(self):
        with self.assertRaises(Denied):
            decode('{"a":1,"a":2}')
        with self.assertRaises(Denied):
            decode("NaN")
        with self.assertRaises(Denied):
            decode("1e999")
        with self.assertRaises(Denied):
            decode(b"\xff\xfe")
        with self.assertRaises(Denied):
            decode(" " * 65537)
        with self.assertRaises(Denied):
            decode(12345)
        self.assertEqual(decode('{"a":[1,2.5]}'), {"a": [1, 2.5]})

    def test_canonical_is_stable_and_rejects_nonfinite(self):
        self.assertEqual(canonical({"b": 1, "a": 2}), b'{"a":2,"b":1}')
        with self.assertRaises(ValueError):
            canonical(float("nan"))

    def test_digest_is_canonical(self):
        self.assertEqual(digest({"b": 1, "a": 2}), digest({"a": 2, "b": 1}))
        self.assertNotEqual(digest({"a": 2}), digest({"a": 3}))

    def test_tag_requires_full_key_and_check_signature_binds_domain(self):
        with self.assertRaises(Denied):
            tag(b"short", "receipt-v1", {"a": 1})
        with self.assertRaises(Denied):
            tag("r" * 32, "receipt-v1", {"a": 1})
        body = {"a": 1}
        signature = tag(RECEIPT, "receipt-v1", body)
        check_signature(RECEIPT, "receipt-v1", body, signature)
        with self.assertRaises(Denied):
            check_signature(RECEIPT, "submit-v2", body, signature)
        with self.assertRaises(Denied):
            check_signature(RECEIPT, "receipt-v1", {"a": 2}, signature)
        with self.assertRaises(Denied):
            check_signature(RECEIPT, "receipt-v1", body, 123)
        with self.assertRaises(Denied):
            check_signature(b"x" * 32, "receipt-v1", body, signature)

    def test_contract_validate_accepts_fixture_and_rejects_drift(self):
        self.assertIsNone(self.contract.validate(self.req, time.time()))
        for mutate in (
            lambda r: r.update({"deadline": time.time() + 301}),
            lambda r: r.update({"deadline": time.time() - 1}),
            lambda r: r.update({"issue": "00000000-0000-0000-0000-000000000000"}),
            lambda r: r.update({"issue": str(fixtures.uuid.uuid4()).upper()}),
            lambda r: r.update({"idempotency_key": "has spaces"}),
            lambda r: r.update({"task": "x" * 4097}),
            lambda r: r.update({"fence": 0}),
            lambda r: r["lineage"].update({"depth": 1}),
            lambda r: r.update({"policy": "other-policy"}),
            lambda r: r.update({"extra": 1}),
        ):
            req = fixtures.request()
            mutate(req)
            with self.assertRaises(Denied, msg=mutate):
                self.contract.validate(req, time.time())


class ReceiptValidationTests(fixtures.CandidateCase):
    def test_success_validation_unit_only_not_fleet_acceptance(self):
        # Signed semantic fixture tests the verifier, never establishes a real runtime.
        body = {
            key: self.req[key]
            for key in (
                "attempt",
                "company",
                "project",
                "issue",
                "run",
                "origin_thread",
                "fence",
                "policy",
            )
        }
        body.update(
            request_digest=digest(self.req),
            state="succeeded",
            exit_code=0,
            actual_model=MODEL,
            actual_provider=PROVIDER,
            version=1,
            accepted=0.5,
            started=1,
            finished=2,
            reason="",
            artifacts={"fixture.txt": "b" * 64},
            evidence=[
                {
                    "kind": "task-verification",
                    "passed": True,
                    "request_digest": digest(self.req),
                    "scope": "UNIT ONLY",
                }
            ],
        )
        envelope = {"body": body, "signature": tag(RECEIPT, "receipt-v1", body)}
        self.assertEqual(validate_success(envelope, self.req, RECEIPT), body)
        for change in [
            {"state": "unknown"},
            {"state": "finished"},
            {"actual_model": "gpt-6-astra"},
            {"actual_provider": "openrouter"},
            {"artifacts": {}},
            {"issue": str(uuid.uuid4())},
            {"request_digest": "c" * 64},
            {"exit_code": True},
            {"finished": 0},
        ]:
            bad = dict(body, **change)
            with self.assertRaises(Denied):
                validate_success(
                    {"body": bad, "signature": tag(RECEIPT, "receipt-v1", bad)},
                    self.req,
                    RECEIPT,
                )
        with self.assertRaises(Denied):
            validate_success({"status": "success", "exit_code": 0}, self.req, RECEIPT)
        with self.assertRaises(Denied):
            validate_success({"body": body, "signature": "0" * 64}, self.req, RECEIPT)

    def test_terminal_window_rules(self):
        body = self.success_body()
        late = {**body, "finished": body["finished"] + 400}
        with self.assertRaises(Denied):
            validate_terminal(late, self.req)
        unstarted = {**body, "started": None}
        with self.assertRaises(Denied):
            validate_terminal(unstarted, self.req)
        no_exit = {**body, "exit_code": None}
        with self.assertRaises(Denied):
            validate_terminal(no_exit, self.req)
        # Late failure reconciliation is allowed; only success is time-boxed.
        failed = {
            **body,
            "state": "failed",
            "started": None,
            "exit_code": None,
            "actual_model": None,
            "actual_provider": None,
            "artifacts": {},
            "evidence": [],
            "finished": body["finished"] + 400,
        }
        self.assertEqual(validate_terminal(failed, self.req), failed)

    def test_terminal_identity_and_evidence_binding(self):
        body = self.success_body()
        wrong_digest = {**body, "request_digest": "0" * 64}
        with self.assertRaises(Denied):
            validate_terminal(wrong_digest, self.req)
        bad_kind = {
            **body,
            "evidence": [
                {**body["evidence"][0], "kind": "fleet-acceptance"},
            ],
        }
        with self.assertRaises(Denied):
            validate_terminal(bad_kind, self.req)
        foreign = {**body, "company": str(fixtures.uuid.uuid4())}
        with self.assertRaises(Denied):
            validate_terminal(foreign, self.req)


if __name__ == "__main__":
    unittest.main(verbosity=2)
