# Consolidation method — thread 184991

Sanitized description of the operating method used by the Paperclip
executor/connector program. Host names, network identifiers, account
paths, and credential material are intentionally omitted.

## Authenticated connector admission contract

A host connector is admitted only when all of the following hold against
the real endpoint:

1. Missing credential → HTTP 401.
2. Wrong credential → HTTP 401.
3. Correct connector-only credential → HTTP 200 with a nonempty
   models-list response.
4. TLS verification is mandatory for non-loopback endpoints; redirects
   and proxies are disabled; plaintext HTTP is permitted only for literal
   loopback test addresses.
5. The public `/health` route is never used as evidence — a health check
   passing while authenticated routes return 401 is a known false
   positive and was reproduced against a real installed adapter.

Provider credentials are never copied between hosts. Each host receives a
dedicated, newly created connector-only credential, stored owner-only,
bound to a private loopback or authenticated private-network route.

## Evidence-gated review flow

Every candidate followed the same pipeline:

1. Sole-ownership lease recorded before any write; all other sources
   read-only.
2. Real tests only — loopback HTTP and verified-TLS suites executed
   against the exact candidate source; no mocks of the thing under test.
3. Independent security review of the exact commit SHA, not a
   description of it. Rejections freeze the baseline read-only; fixes
   land in a new candidate that re-runs the full gate.
4. Parent reproduction: the reviewer’s tests are re-executed by the
   integrating owner against the exact same SHA before acceptance.
5. Acceptance is scoped: “accepted for admission integration only” does
   not imply installation, service-origin admission, or execution
   qualification.

## Containment qualification gates (still open)

The executor/runtime candidates remain unqualified until, at minimum:

- an externally enforced, dedicated nonprivileged worker boundary exists;
- positive useful-work execution and negative denial tests (filesystem,
  secret, socket, network, nested dispatch) pass under that boundary;
- durable correlated receipts survive restart and are independently read
  back.

Until then, every executor artifact in this directory is prototype
material, regardless of how green its unit tests are.
