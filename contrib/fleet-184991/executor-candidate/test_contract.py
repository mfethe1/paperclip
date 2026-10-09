"""Controller/contract admission tests: grants, scope, schema, cancellation."""

import copy
import time
import unittest
import uuid

import executor_fixtures as fixtures
from executor import (
    BLOCKER,
    Denied,
    DisabledBackend,
    decode,
    validate_success,
)
from executor_fixtures import KEY, RECEIPT, authorize


class ContractTests(fixtures.CandidateCase):
    def test_disabled_backend_no_execution(self):
        with self.assertRaisesRegex(Denied, "No qualified"):
            DisabledBackend().launch(self.req)
        result = self.controller.submit(self.req, self.grant())
        self.assertEqual(result["body"]["state"], "failed")
        self.assertIsNone(result["body"]["started"])
        self.assertIsNone(result["body"]["actual_model"])
        self.assertEqual(result["body"]["reason"], BLOCKER)
        with self.assertRaises(Denied):
            validate_success(result, self.req, RECEIPT)

    def test_wrong_tenant_origin_policy_model_lineage(self):
        for field, value in [
            ("company", str(uuid.uuid4())),
            ("project", str(uuid.uuid4())),
            ("origin_thread", "0"),
            ("model", "gpt-6-astra"),
            ("provider", "openrouter"),
            ("policy", "unrestricted"),
            ("base_commit", "A" * 40),
            ("repo", "/elsewhere"),
            ("lineage", {"source": "worker", "role": "leaf", "depth": 1}),
        ]:
            with self.subTest(field=field):
                changed = dict(self.req, **{field: value})
                with self.assertRaises(Denied):
                    self.controller.submit(changed, self.grant(changed))
        self.assertEqual(
            self.ledger.db.execute("SELECT count(*) FROM attempts").fetchone()[0], 0
        )

    def test_malformed_unknown_fields_and_deadline(self):
        for changed in [
            dict(self.req, extra=True),
            dict(self.req, fence=True),
            dict(self.req, deadline=time.time() - 1),
            dict(self.req, deadline=float("inf")),
            dict(self.req, attempt="invalid"),
            dict(self.req, task=""),
        ]:
            with self.assertRaises(Denied):
                self.contract.validate(changed, time.time())
        with self.assertRaises(Denied):
            decode('{"a":1,"a":2}')
        with self.assertRaises(Denied):
            decode('{"a":NaN}')
        with self.assertRaises(Denied):
            decode("not json")

    def test_grant_expiry_binding_and_authentication(self):
        grant = self.grant()
        bad = copy.deepcopy(grant)
        bad["signature"] = "0" * 64
        with self.assertRaises(Denied):
            self.controller.submit(self.req, bad)
        with self.assertRaises(Denied):
            self.controller.submit(dict(self.req, task="changed"), grant)
        with self.assertRaises(Denied):
            self.controller.submit(self.req, authorize(self.req, KEY, time.time() - 1))

    def test_conflicting_payload(self):
        self.controller.submit(self.req, self.grant())
        changed = dict(self.req, task="Altered")
        with self.assertRaisesRegex(Denied, "idempotency conflict"):
            self.controller.submit(changed, self.grant(changed))

    def test_cancellation_without_spawn_is_terminal(self):
        self.ledger.admit(self.req)
        receipt = self.ledger.finish(
            self.req["attempt"], 1, "cancelled", reason="cancelled before launch"
        )
        self.assertIsNone(receipt["body"]["started"])
        self.assertEqual(receipt["body"]["state"], "cancelled")
        with self.assertRaises(Denied):
            self.ledger.start(self.req["attempt"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
