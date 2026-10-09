"""Real local subprocess probes, NOT an approved model execution backend.

Never imported by executor.py. OS deny probes do not establish fleet acceptance.
"""

import hashlib
import json
import os
import selectors
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def run_bounded(argv, workspace, timeout=2):
    # Diagnostic only: capped in-memory pipes replace unbounded disk spooling.
    # Ordinary killpg is NOT evidence of stopped detached/hostile descendants.
    workspace = Path(workspace).resolve()
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(workspace),
        "TMPDIR": str(workspace),
        "PYTHONNOUSERSITE": "1",
        "LC_ALL": "C",
    }
    child = subprocess.Popen(
        argv,
        cwd=workspace,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    buffers = {"stdout": bytearray(), "stderr": bytearray()}
    timed_out = exceeded = False
    deadline = time.monotonic() + timeout
    try:
        with selectors.DefaultSelector() as selector:
            for name, stream in (("stdout", child.stdout), ("stderr", child.stderr)):
                selector.register(stream, selectors.EVENT_READ, name)
            while selector.get_map():
                left = deadline - time.monotonic()
                if left <= 0:
                    timed_out = True
                    break
                for key, _ in selector.select(left):
                    data = os.read(key.fileobj.fileno(), 8192)
                    if not data:
                        selector.unregister(key.fileobj)
                    else:
                        dest = buffers[key.data]
                        room = 65536 - len(dest)
                        dest.extend(data[:room])
                        if len(data) > room:
                            exceeded = True
                            break
                if exceeded:
                    break
            if not timed_out and not exceeded:
                try:
                    child.wait(timeout=max(0.001, deadline - time.monotonic()))
                except subprocess.TimeoutExpired:
                    timed_out = True
    finally:
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        child.wait(timeout=2)
        child.stdout.close()
        child.stderr.close()
    return {
        "exit_code": child.returncode,
        "timed_out": timed_out,
        "output_limit_exceeded": exceeded,
        "truncated": exceeded,
        "boundary_stop_proven": False,
        "cleanup_scope": "ordinary process group only",
        **{
            name: bytes(value).decode(errors="replace")
            for name, value in buffers.items()
        },
    }


def sandbox_probe(workspace, outside, scoped=False):
    workspace, outside = Path(workspace).resolve(), Path(outside).resolve()
    profile = "(version 1)(deny default)(allow process-exec)(allow sysctl-read)"
    for path in [
        "/opt/homebrew",
        "/System/Library",
        "/usr/lib",
        "/bin",
        "/usr/bin",
        "/dev/null",
        str(workspace),
    ]:
        profile += "(allow file-read* (subpath " + json.dumps(path) + "))"
    profile += "(allow file-write* (subpath " + json.dumps(str(workspace)) + "))"
    if scoped:
        # Diagnostic deny witnesses only: default-allow is NOT qualified containment.
        profile = "(version 1)(allow default)(deny network*)"
        profile += (
            "(deny file-read* file-write* (literal " + json.dumps(str(outside)) + "))"
        )
        profile += '(deny file-read* (subpath "/home/operator/.config/hermes-fleet"))'  # sanitized: original denied the operator's private fleet-config directory
        profile += (
            "(deny file-read* file-write* (literal "
            + json.dumps(str(outside.parent / "control.sock"))
            + "))"
        )
    profile_path = workspace / "probe.sb"
    profile_path.write_text(profile)
    # Every denial must occur at the kernel boundary, not be simulated by Python.
    script = r"""
import json, os, pathlib, socket
w=pathlib.Path(os.environ['HOME']); outside=pathlib.Path(__import__('sys').argv[1])
r={}
(w/'artifact.txt').write_text('real local sandbox artifact\n'); r['positive_write']=True
for name,fn in {
 'outside_read':lambda:outside.read_text(),
 'outside_write':lambda:outside.write_text('CHANGED'),
 'symlink_read':lambda:(w/'escape').read_text(),
 'network':lambda:socket.create_connection(('127.0.0.1',3101),timeout=1),
 'socket':lambda:socket.socket(socket.AF_UNIX).connect(str(outside.parent/'control.sock')),
 'nested_dispatch_read':lambda:pathlib.Path('/home/operator/.config/hermes-fleet/fleet-dispatch.py')  # sanitized: original read the operator's private fleet-dispatch client.read_text(),
}.items():
 try: fn(); r[name]={'denied':False}
 except OSError as e: r[name]={'denied':e.errno in (1,13),'errno':e.errno}
r['environment_clean']=not any(k in os.environ for k in ('PAPERCLIP_API_KEY','OPENAI_API_KEY','HERMES_EXECUTION_CONTEXT'))
print(json.dumps(r,sort_keys=True))
"""
    (workspace / "escape").symlink_to(outside)
    with socket.socket(socket.AF_UNIX) as witness_socket:
        witness_socket.bind(str(outside.parent / "control.sock"))
        witness_socket.listen(1)
        return run_bounded(
            [
                "/usr/bin/sandbox-exec",
                "-f",
                str(profile_path),
                sys.executable,
                "-c",
                script,
                str(outside),
            ],
            workspace,
            5,
        )


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(
        prefix="paperclip-os-probe-", dir=os.environ["TMPDIR"]
    ) as root:
        root = Path(root)
        work = root / "task"
        work.mkdir()
        witness = root / "outside.txt"
        witness.write_text("UNCHANGED")
        result = sandbox_probe(work, witness, scoped="--scoped" in sys.argv)
        result["probe_kind"] = (
            "scoped-deny-witness-only"
            if "--scoped" in sys.argv
            else "strict-profile-unqualified"
        )
        result["host_witness_unchanged"] = witness.read_text() == "UNCHANGED"
        artifact = work / "artifact.txt"
        result["artifact_sha256"] = (
            hashlib.sha256(artifact.read_bytes()).hexdigest()
            if artifact.exists()
            else None
        )
        print(json.dumps(result, sort_keys=True))
