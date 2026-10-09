"""Review a3bb8cd F4/F5 terminal/authority regressions: receipts, running release."""

import unittest

import executor_fixtures as fixtures
from executor import (
    MODEL,
    PROVIDER,
    Denied,
    digest,
    tag,
    validate_success,
)
from executor_fixtures import (
    COMPANY,
    KEY,
    PROJECT,
    PUBLIC,
    RECEIPT,
    authorize_status,
)


class TerminalRegressions(fixtures.CandidateCase):
    def test_F4_writer_rejects_unstructured_success_before_commit(self):
        self.ledger.admit(self.req)
        self.ledger.start(self.req["attempt"], 1)
        with self.assertRaises(Denied):
            self.ledger.finish(
                self.req["attempt"],
                1,
                "succeeded",
                exit_code=0,
                artifacts={"fake.txt": "c" * 64},
                evidence=["unchecked"],
                actual_model=MODEL,
                actual_provider=PROVIDER,
            )
        self.assertEqual(
            self.ledger.lookup(self.req["attempt"], COMPANY, PROJECT)["state"],
            "running",
        )

    def test_F4_exact_terminal_schema_and_numeric_types(self):
        body = self.success_body()
        for change in (
            {"version": 999},
            {"authority": "new"},
            {"fence": True},
            {"started": -2},
            {"finished": self.req["deadline"] + 1},
            {"artifacts": {"..": "c" * 64}},
        ):
            with self.subTest(change=change), self.assertRaises(Denied):
                bad = dict(body, **change)
                validate_success(
                    {"body": bad, "signature": tag(RECEIPT, "receipt-v1", bad)},
                    self.req,
                    RECEIPT,
                )

    def test_F5_running_cancel_without_supervisor_retains(self):
        self.ledger.admit(self.req)
        self.ledger.start(self.req["attempt"], 1)
        result = self.ledger.finish(
            self.req["attempt"], 1, "cancelled", reason="no stop proof"
        )
        self.assertEqual(result["body"]["state"], "unknown")

    def test_F5_every_running_release_uncertain_is_unknown(self):
        for state in ("failed", "cancelled", "succeeded"):
            with self.subTest(state=state):
                req = fixtures.request()
                self.ledger.admit(req)
                self.ledger.start(req["attempt"], 1)
                kwargs = (
                    {}
                    if state != "succeeded"
                    else {
                        "exit_code": 0,
                        "actual_model": MODEL,
                        "actual_provider": PROVIDER,
                        "artifacts": {"fixture.txt": "c" * 64},
                        "evidence": [
                            {
                                "kind": "task-verification",
                                "passed": True,
                                "request_digest": digest(req),
                                "scope": "UNIT ONLY",
                            }
                        ],
                    }
                )
                result = self.ledger.finish(req["attempt"], 1, state, **kwargs)
                self.assertEqual(result["body"]["state"], "unknown")
                replacement = dict(
                    req,
                    attempt=str(fixtures.uuid.uuid4()),
                    idempotency_key=fixtures.uuid.uuid4().hex,
                    fence=2,
                )
                with self.assertRaises(Denied):
                    self.ledger.admit(replacement)

    def test_authority_public_verifier_cannot_mint_or_cross_domain(self):
        import executor

        self.assertFalse(hasattr(executor, "authorize"))
        body = self.grant()["body"]
        forged = {"body": body, "signature": tag(PUBLIC, "submit-v2", body)}
        with self.assertRaises(Denied):
            self.controller.submit(self.req, forged)
        with self.assertRaises(Denied):
            self.controller.submit(
                self.req, authorize_status(self.req, KEY, self.req["deadline"])
            )
        self.assertEqual(
            self.ledger.db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0], 0
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
