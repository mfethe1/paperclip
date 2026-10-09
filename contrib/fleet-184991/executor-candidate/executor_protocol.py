"""Private candidate: authenticated admission and receipts; execution stays closed.

Protocol half of the executor prototype: canonical encoding, digests,
authentication tags, the host-owned contract allowlist and terminal receipt
validation. Pure functions and data only — no host IO, no database — so this
module is reviewable and testable independently of the ledger and controller.
No bridge code is copied. This is not a network service or a fleet dispatcher.
"""

import hashlib
import hmac
import json
import math
import re
import uuid

from security import Denied, finite_number

POLICY = "paperclip-contained-v1-disabled"
MODEL = "gpt-6.1-sol"
PROVIDER = "openai-codex"
TERMINAL = {"succeeded", "failed", "cancelled", "unknown"}
BLOCKER = (
    "No qualified nonprivileged worker boundary plus host-owned OAuth broker "
    "for gpt-6.1-sol/openai-codex; existing bridge routes are Astra/GLM, "
    "not the approved runner. No execution backend is enabled."
)
FIELDS = {
    "company",
    "project",
    "issue",
    "run",
    "origin_thread",
    "approval_scope",
    "repo",
    "base_commit",
    "policy",
    "attempt",
    "fence",
    "deadline",
    "idempotency_key",
    "model",
    "provider",
    "lineage",
    "task",
}

TERMINAL_FIELDS = {
    "version",
    "attempt",
    "company",
    "project",
    "issue",
    "run",
    "origin_thread",
    "fence",
    "request_digest",
    "policy",
    "state",
    "accepted",
    "started",
    "finished",
    "exit_code",
    "actual_model",
    "actual_provider",
    "artifacts",
    "evidence",
    "reason",
}


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def decode(raw):
    if (
        type(raw) not in (str, bytes)
        or len(raw if type(raw) is bytes else raw.encode()) > 65536
    ):
        raise Denied("input too large")

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise Denied("duplicate JSON key")
            result[key] = value
        return result

    def constant(_):
        raise Denied("non-finite JSON")

    try:

        def number(text):
            value = float(text)
            if not math.isfinite(value):
                raise Denied("non-finite JSON number")
            return value

        return json.loads(
            raw, object_pairs_hook=pairs, parse_constant=constant, parse_float=number
        )
    except (ValueError, RecursionError) as error:
        raise Denied("invalid JSON") from error


def tag(key, domain, value):
    if not isinstance(key, bytes) or len(key) < 32:
        raise Denied("signing key unavailable")
    return hmac.new(
        key, domain.encode() + b"\x00" + canonical(value), hashlib.sha256
    ).hexdigest()


def check_signature(key, domain, value, signature):
    if not isinstance(signature, str) or not hmac.compare_digest(
        tag(key, domain, value), signature
    ):
        raise Denied("authentication failed")


class Contract:
    """Host-owned immutable allowlist, never sourced from task prose."""

    def __init__(self, company, project, repo, base_commit):
        self.company, self.project = company, project
        self.repo, self.base_commit = repo, base_commit

    def validate(self, request, now):
        if not isinstance(request, dict) or set(request) != FIELDS:
            raise Denied("request schema mismatch")
        for name in ("company", "project", "issue", "run", "attempt"):
            value = request[name]
            if not isinstance(value, str):
                raise Denied("invalid identifier")
            try:
                if str(uuid.UUID(value)) != value:
                    raise Denied("noncanonical identifier")
            except ValueError as error:
                raise Denied("invalid identifier") from error
        for name in ("issue", "run", "attempt"):
            if request[name] == "00000000-0000-0000-0000-000000000000":
                raise Denied("nil identifier")
        expected = {
            "company": self.company,
            "project": self.project,
            "repo": self.repo,
            "base_commit": self.base_commit,
            "origin_thread": "184991",
            "approval_scope": "local-artifact-only",
            "policy": POLICY,
            "model": MODEL,
            "provider": PROVIDER,
        }
        if any(request[name] != value for name, value in expected.items()):
            raise Denied("request outside host allowlist")
        if not re.fullmatch(r"[0-9a-f]{40}", request["base_commit"]):
            raise Denied("invalid base commit")
        if type(request["fence"]) is not int or not 1 <= request["fence"] <= 2147483647:
            raise Denied("invalid fence")
        deadline = request["deadline"]
        if not finite_number(deadline) or not now < deadline <= now + 300:
            raise Denied("invalid deadline")
        if not isinstance(request["idempotency_key"], str) or not re.fullmatch(
            r"[A-Za-z0-9_-]{1,100}", request["idempotency_key"]
        ):
            raise Denied("invalid idempotency key")
        if (
            type(request["lineage"]) is not dict
            or type(request["lineage"].get("depth")) is not int
            or request["lineage"]
            != {
                "source": "paperclip-controller",
                "role": "controller",
                "depth": 0,
            }
        ):
            raise Denied("nested/worker admission refused")
        if (
            not isinstance(request["task"], str)
            or not 1 <= len(request["task"]) <= 4096
        ):
            raise Denied("invalid task")


def validate_terminal(body, request):
    if type(body) is not dict or set(body) != TERMINAL_FIELDS:
        raise Denied("terminal schema mismatch")
    if type(body["version"]) is not int or body["version"] != 1:
        raise Denied("unsupported terminal version")
    if type(body["fence"]) is not int or not 1 <= body["fence"] <= 2147483647:
        raise Denied("invalid terminal fence")
    for key in (
        "attempt",
        "company",
        "project",
        "issue",
        "run",
        "origin_thread",
        "policy",
        "fence",
    ):
        if type(body[key]) is not type(request[key]) or body[key] != request[key]:
            raise Denied("receipt identity mismatch")
    if body["request_digest"] != digest(request) or body["state"] not in TERMINAL:
        raise Denied("invalid terminal identity/state")
    accepted, started, finished = body["accepted"], body["started"], body["finished"]
    if (
        not finite_number(accepted)
        or not finite_number(finished)
        or accepted > finished
        or accepted > request["deadline"]
        or (
            started is not None
            and (
                not finite_number(started)
                or not accepted <= started <= min(finished, request["deadline"])
            )
        )
    ):
        raise Denied("incoherent terminal timestamps")
    # Late failure/cancellation/unknown reconciliation is allowed, never late success.
    if body["state"] == "succeeded" and (
        started is None or finished > request["deadline"]
    ):
        raise Denied("success outside execution window")
    if body["exit_code"] is not None and (
        type(body["exit_code"]) is not int or not -255 <= body["exit_code"] <= 255
    ):
        raise Denied("invalid terminal exit code")
    if (
        body["actual_model"] not in (None, MODEL)
        or body["actual_provider"] not in (None, PROVIDER)
        or (body["actual_model"] is None) != (body["actual_provider"] is None)
        or type(body["reason"]) is not str
        or len(body["reason"].encode()) > 2048
    ):
        raise Denied("invalid terminal runtime/reason")
    artifacts, evidence = body["artifacts"], body["evidence"]
    if (
        type(artifacts) is not dict
        or len(artifacts) > 32
        or any(
            type(k) is not str
            or k in (".", "..")
            or not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", k)
            or type(v) is not str
            or not re.fullmatch(r"[0-9a-f]{64}", v)
            for k, v in artifacts.items()
        )
        or type(evidence) is not list
        or len(evidence) > 16
    ):
        raise Denied("invalid bounded artifacts/evidence")
    for item in evidence:
        if (
            type(item) is not dict
            or set(item) != {"kind", "passed", "request_digest", "scope"}
            or item["kind"] != "task-verification"
            or type(item["passed"]) is not bool
            or item["request_digest"] != digest(request)
            or type(item["scope"]) is not str
            or not 1 <= len(item["scope"].encode()) <= 256
        ):
            raise Denied("invalid request-bound task evidence")
    if body["state"] == "succeeded" and (
        body["exit_code"] != 0
        or body["actual_model"] != MODEL
        or body["actual_provider"] != PROVIDER
        or not artifacts
        or not any(item["passed"] is True for item in evidence)
    ):
        raise Denied("success lacks verified runtime/artifact evidence")
    if len(canonical(body)) > 65536:
        raise Denied("terminal receipt too large")
    return body


def validate_success(envelope, request, receipt_key):
    if type(envelope) is not dict or set(envelope) != {"body", "signature"}:
        raise Denied("not an authenticated terminal receipt")
    check_signature(receipt_key, "receipt-v1", envelope["body"], envelope["signature"])
    body = validate_terminal(envelope["body"], request)
    if body["state"] != "succeeded":
        raise Denied("not succeeded")
    return body
