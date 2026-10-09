# Contained executor candidate — local-only, execution disabled

## Canonical verification

```sh
cd contrib/fleet-184991/executor-candidate
python3 verify.py
```

Uses installed Python, Ruff, and cryptography Ed25519 verification (46.0.4 available locally). Missing cryptography fails authentication closed. Logs are under `evidence/`. `python3 discover.py` repeats **read-only** host/SSH provenance discovery and bridge status; it never calls `ask`. No packages, service installation or credentials are required. Test signing keys and project/repository/base identifiers are explicitly local test values, not enrolled fleet credentials or real Paperclip authorization.

## Implemented contract

`executor.py` provides exact-schema validation, company/project/repo/base allowlists, binding to thread `184991`, `local-artifact-only` approval, immutable policy and the exact `gpt-6.1-sol` / `openai-codex` identities. UUIDs, deadlines, fence, idempotency key, task size and controller lineage are checked without normalizing invalid identifiers. Signed, expiring controller grants bind the entire canonical request digest. Receipt signing uses a separate key/domain. The CLI cannot mint grants.

SQLite uses real `BEGIN IMMEDIATE`, WAL and synchronous FULL. A tenant-scoped unique idempotency key and partial unique index enforce one accepted/running/unknown reservation per issue. Fences monotonically advance only within the same committed admission. Duplicate delivery returns the existing identity/result; conflicting reuse fails. Receipt insertion and terminal state transition commit together. Triggers prohibit receipt modification/deletion and terminal/identity mutation through the normal ledger API.

Accepted/running crashes reconcile to signed `unknown`, retaining the reservation. Every requested terminal release from `running` also becomes `unknown`: no qualified stop/broker-revocation proof channel is implemented, so caller cancellation/failure/success assertions cannot release capacity. There is no automatic replay, replacement, lease expiry or unknown-release operation. Host-held artifact files and DB commits are **not** claimed atomic: an artifact after a crash is not success evidence. Explicit reviewed reconciliation is required.

`client.py` is a local transport entrypoint, **not a wired Paperclip process adapter**. F1 remains blocked on trusted request/context retrieval and controller-issued grants:

```text
<absolute-python> <absolute-candidate>/client.py <host-owned-private-config.json>
```

It accepts one EOF-delimited JSON frame (64 KiB, 2-second wall-clock cap), never interpolates task text into a shell, and requires an explicit `operation`. Submit uses `{operation: "submit", request, grant}` and exits 0 only after matching authenticated success. Status uses `{operation: "status", query, grant}` with a fresh domain-separated authorization and read-only ledger connection; its exit 0 means transport success, not task success. Production execution always returns a signed failure and exit 2. Missing/malformed/private-configuration failures remain nonzero. No adapter, agent or service has been registered.

Host configuration fields: `company`, `project`, `repo`, `base_commit`, `database`, `keys_file`. The key file contains exact 32-byte lower-case hex `controller_public`/`receipt` values. Only the Ed25519 public controller key is supplied to the executor; controller private signing material exists solely in disposable test fixtures. Grant domains are `submit-v2` and `status-v2`; receipt HMAC remains `receipt-v1`, owned by the supervisor. These files must be owner-only, non-symlink, and host-controlled. There is deliberately no shipped real configuration, credential enrollment flow, enabled flag, shell command field or bridge-submission path. An independent protected service identity and secret separation remain deployment gates; this local same-UID candidate is not that boundary.

## Containment evidence and limitation

`probe_runner.py` is a standalone diagnostic **never imported by the controller**. It runs real short-lived subprocesses with a small environment, local files, timeout and ordinary process-group cleanup. It is not a model worker backend and does not prove cleanup of hostile detached/session-escaping descendants or resource confinement.

The strict default-deny Seatbelt profile aborts the installed Python runtime with return code `-6` before producing an artifact. This is a measured unqualified-profile result, not a claim that Seatbelt itself is unavailable.

A separately labeled **default-allow scoped deny-witness profile** proves positive task-local write and actual OS permission denials for outside witness read/write, symlink escape, loopback network, an existing task-owned Unix control socket, and reading the fleet-dispatch client. The original outside file is unchanged. Denying client-file read is not proof that every nested-dispatch mechanism is blocked. This diagnostic profile allows unrelated operations; it must never be used as production containment.

The backend remains unconditionally disabled: a qualified nonprivileged worker boundary, complete filesystem/secret/socket/network restrictions, narrow host-owned OAuth broker, resource supervision and exact approved runner are not present in this candidate. Tests of synthetic signed success receipts validate matching logic only; they are explicitly not fleet acceptance.

## Provenance

Read plan and fleet federation charter are retained in the private program record (withheld: private host paths). Latest explicit approved model/provider overrides the historical charter's provider default. No shared claims or registry were changed; ownership was assigned by the parent.

Host and installed-bridge provenance was captured read-only during discovery and is retained in the private evidence record (withheld: host names and account paths). No bridge code was copied.

The surrounding agent-configuration Git HEAD did **not** establish bridge source provenance because the bridge runner was Git-ignored; installed/source runner, receipts and adapter hashes were matched directly during discovery. The observed routing policy contains Astra and GLM identities, not `gpt-6.1-sol` / `openai-codex`; no route, hold, reservation or service was modified. The existing root-handoff guards are untouched.

## Independent enablement gates

1. Review the exact local candidate SHA, including same-UID/key/DB threat assumptions, replay/grant authority and safe error/log bounds; parent reruns decisive tests.
2. Enroll a distinct authorized controller/service identity through approved channels; validate exact real Paperclip issue/run context and effective privileges.
3. Qualify dedicated task-only containment and host-owned OAuth broker for the exact approved runner; prove all outside-resource/secret/network/nested-dispatch denials and detached-tree cleanup.
4. Add durable bounded artifact publication and structured verification tied to the request; qualify real successful runtime receipts, cancellation, unknown reconciliation and restart recovery.
5. Wire a new restricted process-adapter agent through the parent, not the historical `hermes_local` agent. Read back exact agent, run, issue and artifact outcome. Then independently qualify Buzz projection and other host lanes.

No strict type checker was available (`mypy` absent), and installing one was prohibited. Syntax and lint checks are not called strict type checking. No push/publication/deployment or live fleet execution is authorized by this candidate.
