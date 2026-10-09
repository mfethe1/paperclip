# Fleet consolidation — thread 184991

Authored work from Michael Feth's Paperclip executor/connector program
(thread 184991), consolidated into this repository for review and
publication. Everything under this directory is **candidate or reference
code** — nothing here is installed, deployed, wired into the Paperclip
server, or qualified for fleet execution.

## Status distinctions (read before using anything)

| Path | Status | Meaning |
|------|--------|---------|
| `connector-admission/` | **REVIEWED — ACCEPT** (narrow) | Independent security review accepted the revised authenticated-admission module for admission integration **only**. Not installed, not activated, no service-origin positive run yet. |
| `connector-admission-rejected/` | **REJECTED** | Original admission baseline. Independent review reproduced secret-bearing HTTP exception propagation and URL route confusion. Preserved for provenance and contrast only — **do not use**. Superseded by `connector-admission/`. |
| `executor-candidate/` | **PROTOTYPE — containment NOT qualified** | Fail-closed executor candidate. Backend unconditionally disabled: no qualified nonprivileged worker boundary, no complete filesystem/secret/socket/network restrictions, no host-owned OAuth broker. Unit tests validate receipt-matching logic only; they are not fleet acceptance. |
| `runtime-candidate/` | **PROTOTYPE — gated on dedicated VM provisioning** | Containment runtime candidate. Real useful-work and externally enforced denial tests remain open blockers. |
| `scripts/` | **SANITIZED** local-dev helpers | Rewritten for publication: no default secrets, no host-specific paths. |
| `tests/` | Gate tests | Manifest, hash, secret-exclusion and reference-integrity checks for this consolidation. |

## Provenance

Each file's exact source path, SHA-256, and (where applicable) source git
commit is recorded in `manifest.json`. Source repositories were private
local candidates authored by Michael Feth; the key source commits are:

- `connector-admission/` — revised candidate `4e789b8a01efa605dcd203380b4d64878bf2699c`
  (branch `feature/hermes/auth-admission-revised`)
- `connector-admission-rejected/` — rejected baseline `8d20d5fc8af7275fdc969f04b05c1423e4cc9619`
- `executor-candidate/` — candidate `0946287505960f2190e2d0192d5a4f6b56d4a007`
- `runtime-candidate/` — candidate `b1509436a5f1c22752fc1a631afdd8836deb967a`

## What was deliberately excluded

The private program directory contains operational evidence that is **not
publication-safe** and was excluded from this consolidation: raw JSON
evidence/readbacks with private host identifiers, database dumps and
exports, live gateway/profile state, credential-adjacent configuration,
host-specific one-off repair scripts, and operational docs containing
private host names, network identifiers, and account paths. A private
exhaustive inventory (every source file hashed, with include/exclude
rationale) is retained by the program owner; nothing was silently omitted.

## Security notes

- `connector-admission/` logs fixed error categories only. Never extend it
  to log recursive exception contexts or captured locals — those are
  secret-bearing. Shape validation is not strict whole-document JSON
  validation.
- The executor and runtime candidates are published for review and reuse
  of their contracts and tests. Their open qualification blockers are
  stated in their READMEs; treat every "disabled"/"unqualified" statement
  as load-bearing.
