# RUNTIME RESULT — blocked, all execution closed

Read independent `EXECUTOR-REVIEW.md` lines 110–154, especially 122–148.
No dedicated runtime is provisioned or qualified. No real OAuth model task ran.
No live Paperclip/Buzz/API/registry/bridge write or executor source edit occurred.

## Steering applied

The unrelated `buildbid-test-20261002` VM must not be reused. Before that ownership
constraint arrived, this task ran disposable bubblewrap tests on that existing
VM: useful artifact, filesystem/symlink/socket/environment/dispatch denials and
actual fork+setsid cleanup passed. **Those results are historical experiments,
not accepted dedicated-runtime qualification.** All task temporary directories
were automatically removed by the last completed test. No VM stop, restart,
configuration edit or cleanup command was issued after the constraint arrived.

`runtime.py` now names only the nonexistent dedicated target
`paperclip-executor-184991`, sets `DEDICATED_RUNTIME_QUALIFIED=False`, and refuses
all transport/command/cancel execution before spawning anything. OAuth remains
closed. Historical real-runtime tests are retained in `qualification_tests.py`
(not default test discovery); evidence identifies what actually happened, not
authority to integrate. `guest.py` remains isolated prototype source. It must be
adapted to a dedicated VM and independently reviewed, not enabled by flipping a
flag. No executor diagnostic `run_bounded` code was adopted; PID namespaces were
used in the experiments, and real setsid children were exercised.

## Exact minimum provisioning approval requested

A fresh, task-dedicated **Lima Linux ARM64 VM**, using installed Apple
Hypervisor/Lima, with two vCPUs, 2GiB RAM, 10GiB virtual disk, no host mounts,
container engine socket, SSH-agent forwarding, shared home/repo, port forwards,
or provider/signing credentials. Immutable boot image must include Python,
bubblewrap, libseccomp and cgroup v2; a non-root task identity and task-only
writable storage are needed. No download or provisioning is authorized yet.

Verified installed `limactl start --help` provides `--plain`, `--mount-none`,
`--containerd none`, CPU/memory/disk/architecture/VM type and explicit instance
name. Minimum approved launch operation, **not executed**, after approving and
staging a pinned boot image/config with immutable runtime dependencies:

```
/opt/homebrew/bin/limactl start --name=paperclip-executor-184991 \
  --vm-type=vz --arch=aarch64 --cpus=2 --memory=2 --disk=10 \
  --plain --mount-none --containerd=none \
  <private-program>/runtime/provisioning/dedicated.yaml  # sanitized path
```

`dedicated.yaml` and its qualified image do not exist yet. Image acquisition
(one pinned Linux ARM64 image plus any explicitly approved baked dependencies)
is part of the requested approval, not an implicit fallback download. Do not
copy the unrelated machine's writable disk or OAuth files. Installed Lima
reported no instance; there is no available qualified dedicated VM. Local cached
Podman base-image discovery does not establish a Lima-compatible approved image.

Impact: one isolated VM process, up to two vCPUs/2GiB active RAM and 10GiB virtual
disk, boot-image storage/download, and local-only manager/SSH control transport.
No LAN/tailnet ingress or global Docker/Podman/auth configuration change is
needed. Network is bootstrap-only explicitly approved acquisition; sealed worker
network must then be externally denied except an expiring approved broker path.
A whole per-task VM boundary teardown provides final descendant cleanup.

## Other exact runtime prerequisite

The cgroup experiment created a disposable task group and wrote its limits, but
moving an SSH-launched worker from `session-38.scope` into the delegated
`user@501.service` subtree failed `PermissionError [Errno 13]`;
`evidence/cgroup-probe.txt` reproduces it. The group was removed. A new dedicated
supervisor must own a delegated task subtree/start context and prove aggregate
memory/CPU/PID, wall-clock, disk and output limits. Per-process RLIMITs do not
satisfy that acceptance. Existing prototype explicitly reports aggregate false.

A reviewed host-owned read-only OAuth broker is also absent. Pi's offline
no-refresh readiness for `openai-codex/gpt-6.1-sol` is only auth metadata, not a
provider call or broker compatibility proof. No credentials were copied, exposed,
enrolled or refreshed. The broker must pin the actual provider/model, accept only
bounded provider protocol under attempt/fence/deadline, and never become a generic
URL proxy/tool executor. See review 138. Enrollment/refresh requires separate
explicit authorized masked flow if the chosen runner cannot use existing
read-only brokered auth.

## Parent integration contract — disabled

`run_command(code: str <=65536 bytes, timeout: int 1..10, token: canonical UUID)`
currently raises `DEDICATED_RUNTIME_UNPROVISIONED`. `run_model_task` raises
`OAUTH_BROKER_UNQUALIFIED`. CLI request is exact `{code, timeout, token}`; no
receipt or model identity is fabricated. The independent executor owner handles
adapter stdin, ledger/path/schema/receipt/cancel/recovery defects; this candidate
does not overlap that work. Controller authority, receipt keys and genuine
lineage/admission remain distinct prerequisites, not signature fixtures.

## Files and verification

- `runtime.py`, `guest.py`: isolated disabled host/VM prototype.
- `qualification_tests.py`: archived real namespace adversarial tests, not enabled.
- `test_runtime.py`: current fail-closed and strict-input tests, no VM interaction.
- `evidence/`: historical experiments, cgroup denial and current closed gate output.
- `evidence/closed-gates.txt`: current unittest, Ruff and compileall results.

Historical experiment gates must not be cited as dedicated runtime acceptance.
Current code is not production-ready; backend stays disabled pending provisioning,
real broker/artifact task, resource/recovery acceptance and exact-SHA review.
The requested 15-minute delivery budget was exceeded during experimentation.
