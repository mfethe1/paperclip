# Thread 184991 consolidation audit

## Base reconciliation

The first private checkout used upstream Paperclip commit
`2e09570ce09d0fe478b742f2956baa5bc3fc930a` because `mfethe1/paperclip`
was read as empty. During this work a parent readback found a new default
branch `claude/keen-goldberg-kxly6t` at
`60da145241700acf6d964395652f7e92f168f5c8` (two commits by a separate
Claude actor, pushed 2026-10-09T13:30:41Z). This branch has 41 tracked
files and no ancestry to the upstream checkout. Its tree contains a
fleet control-plane/company package, migration tooling, docs, scripts and
tests. It has no `contrib/fleet-184991` paths and no exact candidate
path overlap. No attempt was made to overwrite, reset, push, or merge that
branch.

The candidate has not yet been published. It is prepared as 24 local slices
on top of the exact remote branch tip above; each slice still requires
publication, exact-head hosted checks, and merge qualification. The manifest
records that base SHA; all candidate paths are under `contrib/fleet-184991/`.
The original upstream-based local branch is retained for traceability. No
writes have been made to either remote as of this audit snapshot.

## Scope and status

This is a consolidation of authored work, not a Paperclip server feature
integration. `contrib/fleet-184991/README.md` preserves distinctions:

- revised connector admission: independent review accepted for admission
  integration only; no service-origin positive admission or activation;
- original connector admission: rejected and frozen for provenance;
- executor: prototype, backend closed; containment not qualified;
- runtime: prototype; dedicated VM not provisioned.

No candidate was installed or deployed. No Paperclip API, credentials,
services, agents, task queues, or external boards were changed.

## Exhaustive private inventory

The separate owner-private exhaustive source inventory (not included in this
public repository) contains 3,976 regular-file records discovered in the exact source roots
and ancillary files enumerated in the parent task, each with SHA-256,
source path, byte count, and a disposition/rationale. It does not contain
file contents or credential values. It excludes two live Unix sockets
(which cannot be hashed) and records one missing/dangling skill source.
Counts by disposition:

| Disposition | Count |
|---|---:|
| live Paperclip profile state (all excluded) | 3,667 |
| curated program code/docs (reviewed individually) | 64 |
| private diagnostics/payloads (excluded) | 73 |
| private operational evidence (excluded) | 67 |
| private operational documents (excluded) | 27 |
| private method/one-off scripts (excluded or distilled) | 26 |
| generated/cache/private evidence | 15 |
| host-specific one-off code (excluded) | 16 |
| private skill source (audited, not copied) | 11 |
| sanitized reusable scripts (published rewritten) | 2 |
| private operation/live-state singletons (excluded) | 5 |
| missing/dangling skill source | 3 |

The inventory includes the full private profile tree so coverage is
explicit; config/auth, browser/session state, logs, databases and runtime
artifacts are not copied. Nested executor, admission and runtime Git refs
were read-only inventoried separately; the retained exact candidate SHAs
and their authored provenance are in `manifest.json`. No Git histories or
objects were imported into the public tree.

## Publication-safe coverage

`manifest.json` lists each file under this directory with its published
SHA-256, source path relative to the private program where applicable,
source SHA-256, and `sanitized` flag. Files that derive from a reviewed
source but carry functional changes beyond sanitization are marked
`modified_from_source` with the change described in this audit; their
source SHA-256 provenance is still recorded and enforced. Raw JSON
evidence/readbacks, database dump/export archives, SQLite payloads, logs,
live profile state, private connector/host/client/cadence payloads,
unrelated Paperclip integrations, and host-bound one-off repairs were
deliberately excluded. The only migration material published is the
reusable, sanitized method in `docs/METHOD.md`; portfolio v2 remains an
evidence index, not a board import, and private payload stays private.

## Follow-up remediation (this update)

Two defects blocked publication and were fixed and regression-tested:

1. **SQLite sidecar last-close race (executor ledger).** The owner
   reproduced with a real WAL-churn diagnose loop: SQLite last close may
   unlink `-wal`/`-shm` between the directory lookup and the metadata
   snapshot, so the original open+fstat sidecar validation intermittently
   observed a zero-link regular file and denied a healthy ledger (about
   1/50 opens; 3 denials and 5 queue timeouts in 50 repetitions, and 1/50
   with a first stat-only snapshot). The fix (`security.py`:
   `stat_entry`/`validate_sidecar`/`check_sidecar`) validates one no-follow
   snapshot and rechecks the name exactly once, only for a vanished
   zero-link entry; the skip is permitted solely when the name is gone, and
   every surviving or replaced entry must pass all original
   regular/owner/mode/single-link rules. Deterministic regressions in
   `executor-candidate/test_sidecar.py` use real filesystem objects
   (including a real zero-link fstat of an unlinked open file): no
   removed-file false denial, no mode/link/symlink/directory/fifo bypass,
   persistent zero-link churn fails closed, and 50 repeated ledger
   open/close cycles stay green. All pre-existing hostile storage tests
   are unchanged and still pass.
2. **Dev stop/start script identity handling.** The stop script now reads
   malformed/empty PID records without `set -e` silent exits (fail closed
   with an explicit refusal, record preserved), normalizes `ps` output with
   `LC_ALL=C` plus full leading/trailing whitespace trimming, and the start
   script records the process start identity with exactly the same
   normalization. `tests/test_dev_scripts.py` covers with real subprocesses:
   matching identity stops only the recorded process; stale/wrong identity
   and simulated PID reuse keep the current process; malformed, empty and
   missing-field records fail closed; a missing record is a no-op; a dead
   recorded PID only cleans the record; padded/no-newline records still
   match; a process named `@paperclipai/server` survives (no pattern kill
   exists); the start script refuses to launch without
   `PAPERCLIP_AGENT_JWT_SECRET` or `PAPERCLIP_REPO_DIR`.

**Executor race-test investigation.** The captured failure in `executor/evidence/remediation-after.log` is a test harness scheduling defect, not a demonstrated SQLite defect: `test_separate_process_competing_attempts` received `_queue.Empty` while collecting child outcomes after an immediate gate release. Child ledger initialization was not synchronized, so the fixed per-result queue window included nondeterministic spawn/open time. `race()` now reports readiness after opening its ledger; both multiprocess tests wait until every child is ready before releasing the shared contention gate. This preserves the 10-second bound and all transactional/ownership assertions. Exact-tree post-fix evidence: 20/20 runs of both race tests passed; 10/10 complete executor-suite runs passed (53 tests, 43 subtests each). This establishes the captured timeout's harness cause; it does not qualify executor runtime or establish zero probability of future flakes.

lines) is decomposed into `executor_protocol.py` (294: pure canonical
encoding, contract allowlist, receipt validation), `executor_ledger.py`
(357: durable SQLite ledger, fencing, sidecar identity) and `executor.py`
(233: controller assembly and process adapter). The 480/415-line test files
are split into cohesive groups of at most 300 lines
(`test_protocol/contract/ledger/process/sidecar` plus
`test_remediation_storage/terminal/status`) sharing
`executor_fixtures.py`. The split is behavior-preserving: all original test
bodies moved verbatim except import renaming and lint normalization, and
the pre-existing hostile tests (path replacement, foreign DB, wrong schema,
pipe discipline, cross-tenant status) are unchanged.

**Commit provenance.** The child's commit `0c05de3` ("scope Paperclip dev
process lifecycle") was landed unverified and is **not** claimed as
verified; it and the parent's preliminary sidecar/stop-script fix are
retained on the local ref `fleet-184991/backup-pre-stack` for provenance
only. The verified publication is the 24-slice stack below, built fresh on
the base SHA. Every slice tip ran its own gate; the final slice ran the
full battery.

## Verification and known limits

- Admission real HTTP/TLS tests: 19 passed, 68 subtests.
- Rejected-baseline regression tests: 10 passed, 15 subtests (run
  standalone; its `test_admission.py` basename intentionally collides with
  the reviewed suite under pytest prepend import mode).
- Executor suites: 53 passed, 43 subtests in the recorded final-tree run. A
  prior serial burst had one failure (`test_separate_process_duplicate_transaction`);
  subsequent repeated runs were green, but the failure cause was not recovered.
  Treat executor flakiness as unresolved; do not claim its root cause is fixed.
- Dev-script lifecycle regressions: 12 passed, 7 subtests (real `sleep`
  subprocesses; no host Paperclip process touched).
- Runtime closed-gate tests: 4 passed. Full VM qualification suite is
  intentionally not run because its required dedicated VM does not exist;
  candidate remains unqualified.
- Manifest gates: 7 passed (file coverage, hashes, status distinctions,
  secret/private identifier scans, source-vs-published hash behavior,
  secret-required script contract).
- Ruff: all checks passed. Narrow per-file ignores remain only on three
  immutable, independently reviewed source files whose preserved style is
  part of byte-for-byte provenance; all consolidation-authored and
  decomposed files hold full lint with no ignores.
- Shell: `bash -n` and `shellcheck` clean on both dev scripts.
- `git diff --check` clean on every slice.
- No repository-wide upstream Paperclip build/typecheck was run: this
  candidate is documentation and isolated Python utility code under
  `contrib/`, not a change to server packages. The new remote branch has
  no inherited CI result established by this worker.

## Stacked PR slices

24 commits on base `60da145241700acf6d964395652f7e92f168f5c8`, each under
400 changed lines, each independently green at its own tip:

| Slice | Commit | Content | Gate |
|---|---|---|---|
| S01 | `396cef43c293` | overview README, METHOD, lint policy | diff-check, ruff |
| S02 | `f45e62c54396` | reviewed admission module + README | ruff, import |
| S03 | `6804270bdf16` | admission HTTP/TLS + revision tests | 19 passed |
| S04 | `e84bbb5f16fd` | rejected baseline (frozen provenance) | ruff, import |
| S05 | `334819568078` | rejected-baseline tests | 10 passed |
| S06 | `77fdc2bdddcc` | security (sidecar validation), client, verify | ruff, import |
| S07 | `2740d50d4bd0` | probe runner + candidate docs | ruff, import |
| S08 | `24dbe9aec28b` | executor protocol module | ruff, import |
| S09 | `d60603c40a36` | executor ledger module | ruff, import |
| S10 | `383b9d215190` | executor controller assembly | ruff, import |
| S11 | `ca2642644482` | fixtures + direct protocol tests | 8 passed |
| S12 | `adeacdcf3fb0` | contract + ledger test groups | 12 passed |
| S13 | `b5d4aee456ca` | real subprocess probe/client tests | 4 passed |
| S14 | `5764ec7c30f4` | remediation storage regressions | 6 passed |
| S15 | `f6e1e868c938` | remediation terminal/authority regressions | 5 passed |
| S16 | `21e4c933223f` | remediation status/client regressions | 5 passed |
| S17 | `e33d7e3a000c` | sidecar lifecycle/security regressions | 13 + full 53 passed |
| S18 | `cdb06313bee4` | dev start/stop scripts | bash -n, shellcheck |
| S19 | `4848174029f1` | dev-script lifecycle regressions | 12 passed |
| S20 | `95833817863a` | runtime core + guest prototype | ruff, import |
| S21 | `08ba94fac78e` | runtime closed-gate tests | 4 passed |
| S22 | `8a4b26f7d86b` | runtime qualification suite + result doc | ruff, py_compile |
| S23 | (handoff) | publication manifest | JSON + coverage check |
| S24 | (handoff) | this audit + manifest gate tests | full battery |

A committed document cannot record its own commit hash: the S23/S24 slice
SHAs and the final stack tip are reported in the external handoff receipt
accompanying this branch, alongside the full per-slice gate receipts.

The independent parent security review remains required before any public
write or merge. This worker did not push.
