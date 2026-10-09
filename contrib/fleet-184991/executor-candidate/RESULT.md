# RESULT — first contained-executor candidate

**Outcome:** Substantive standalone candidate implemented and locally verified. Production model/fleet execution remains unconditionally disabled. Not deployed, published, wired to Paperclip or accepted as a contained fleet executor.

## Verification

Canonical command: `python3 verify.py` from this directory.

- **17 tests pass** using real SQLite transactions and separate subprocesses/processes, not mocked locking.
- Tests cover duplicate and competing admissions, altered requests, tenant/model/provider/origin/lineage rejection, expiration/authentication, fencing, persistence/reopen, immutable terminal receipts, kill after admission and kill after artifact before receipt, retained unknown reservation, cancellation before spawn, real local artifact hashing, timeout/ordinary child cleanup, fixed client nonzero exits and replay after a lost reply, malformed and foreign/untrusted success receipts.
- Installed Ruff lint and Python syntax checks pass. Strict type checking was not run: `mypy` is absent and installing packages was prohibited.
- Real scoped OS deny witnesses pass: outside read/write, symlink escape, forbidden loopback network, **existing** Unix socket and dispatch-client file read. Positive task write succeeds, environment has no inherited named API keys, outside witness remains unchanged. This is a diagnostic default-allow profile, **not full containment**.
- Strict default-deny profile exits **-6** with no artifact. The available Seatbelt binary is not enough to qualify the installed runtime. No approved model call occurred.

Logs and machine-readable result: `evidence/tests.log`, `lint.log`, `scoped-os-probe.log`, `strict-os-probe.log`, `summary.json`. Read-only authenticated host/installed-source evidence: `evidence/provenance.json`.

## Files

- `executor.py`: bounded signed controller contract; SQLite admission/idempotency/fences; immutable signed terminal receipts; closed backend; strict success matching.
- `client.py`: fixed process-adapter-compatible entrypoint, bounded input and fail-closed status.
- `probe_runner.py`: explicitly nonproduction subprocess/OS diagnostic probes.
- `test_executor.py`, `verify.py`, `discover.py`: actual tests, canonical evidence generation and read-only provenance discovery.
- `README.md`, `.gitignore`, this report, and evidence files.

## Provenance and blockers

The second host and this host resolved to the same machine; authenticated SSH and bridge status succeeded (host names withheld as private). Installed bridge runner/receipt/adapter hashes are recorded. Bridge source is ignored by the surrounding Hermes Git repository, so that repository HEAD is not claimed as bridge-source provenance. No bridge code was copied.

The running bridge uses Astra/GLM routes rather than the approved `gpt-6.1-sol` / `openai-codex` identity. Nothing was submitted, resumed or modified there. All existing holds/reservations, ordinary root-handoff guards and historical paused-agent state remain untouched.

**Exact execution blockers:** no qualified strict runtime sandbox, dedicated nonprivileged service boundary, host-owned OAuth broker, supervised detached-process/resource containment or verified approved runner. Controller enrollment, real issue/run authority, success/artifact publication and Paperclip/Buzz readback are not yet implemented integrations. Same-UID signed local test grants are not fleet credentials. Diagnostic success and signed semantic fixtures are not fleet acceptance.

**Next gate:** independent security review of the local candidate SHA and parent rerun of verification. Only after the separate runtime, enrollment, authority, containment and live acceptance gates in README may a new restricted process agent be wired. No enable switch exists in this candidate. There is no automatic retry/release of unknown outcomes.

Repository is a new local private candidate on `candidate/contained-executor-184991`, without a remote. The local commit is the report's containing commit (`git rev-parse HEAD`); no push/publication was attempted.
