"""Fixed host-owned, no-credential, no-network command boundary.

Not an admission controller. Only parent-integrated admitted requests may use it.
OAuth/model execution is deliberately unavailable; no generic host-shell route.
"""

import base64
import hashlib
import json
import shlex
import signal
import subprocess
import sys
import uuid
from pathlib import Path

PODMAN = "/opt/homebrew/bin/podman"
MACHINE = "paperclip-executor-184991"
DEDICATED_RUNTIME_QUALIFIED = False
POLICY = "podman-vm-bwrap-v1"
MODEL = "gpt-6.1-sol"
PROVIDER = "openai-codex"


def transport(command, **kwargs):
    if not DEDICATED_RUNTIME_QUALIFIED:
        raise RuntimeError("DEDICATED_RUNTIME_UNPROVISIONED: command execution closed")
    env = {
        "HOME": str(Path.home()),  # sanitized: was a hardcoded operator home path
        "PATH": "/usr/bin:/bin:/opt/homebrew/bin",
        "LANG": "C.UTF-8",
    }
    return subprocess.Popen(
        [PODMAN, "machine", "ssh", MACHINE, command], env=env, **kwargs
    )


def cancel(token):
    if str(uuid.UUID(token)) != token:
        raise ValueError("invalid token")
    source = """
import os,pathlib,signal,sys
root=pathlib.Path('/var/home/core')
token=sys.argv[1]
for d in root.glob('pc-runtime-'+token+'-*'):
 if d.is_symlink() or d.stat().st_uid!=os.getuid(): raise RuntimeError('owner mismatch')
 p=d/'pid'
 if not p.exists(): continue
 pid=int(p.read_text())
 cmd=pathlib.Path('/proc',str(pid),'cmdline').read_bytes()
 if b'/usr/bin/bwrap' not in cmd or token.encode() not in cmd: raise RuntimeError('pid mismatch')
 os.killpg(pid,signal.SIGKILL)
print('cancel-ack')
"""
    cmd = "/usr/bin/env -i /usr/bin/python3 -c " + shlex.quote(source) + " " + token
    child = transport(
        cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    out, _err = child.communicate(timeout=8)
    if child.returncode != 0 or out.strip() != b"cancel-ack":
        raise RuntimeError("cancellation unacknowledged")


def run_command(code, timeout=5, token=None):
    """Execute bounded Python in empty VM mount/net/PID namespace.

    Output is untrusted bounded data. Artifact is fixed artifact.txt, <=1MiB.
    No authority/signatures/model identity are fabricated by this function.
    """
    if not isinstance(code, str) or len(code.encode()) > 65536:
        raise ValueError("bounded code required")
    if type(timeout) is not int or not 1 <= timeout <= 10:
        raise ValueError("timeout must be integer 1..10")
    token = token or str(uuid.uuid4())
    if str(uuid.UUID(token)) != token:
        raise ValueError("canonical UUID required")
    payload = {
        "token": token,
        "timeout": timeout,
        "code": base64.b64encode(code.encode()).decode(),
    }
    source = Path(__file__).with_name("guest.py").read_bytes()
    command = "/usr/bin/env -i /usr/bin/python3 - " + shlex.quote(json.dumps(payload))
    child = transport(
        command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    interrupted = False
    old = {}

    def interruption(signum, frame):
        nonlocal interrupted
        interrupted = True
        cancel(token)

    for sig in (signal.SIGTERM, signal.SIGINT):
        old[sig] = signal.signal(sig, interruption)
    try:
        out, err = child.communicate(source, timeout=timeout + 12)
    except subprocess.TimeoutExpired:
        cancel(token)
        out, err = child.communicate(timeout=8)
        raise RuntimeError("transport timeout; result unknown")
    finally:
        for sig, handler in old.items():
            signal.signal(sig, handler)
    if child.returncode != 0 or len(out) > 1600000:
        raise RuntimeError(
            "guest runtime failure; result unknown: "
            + err.decode(errors="replace")[:2000]
        )
    result = json.loads(out)
    if result.get("token") != token or result.get("runtime") != POLICY:
        raise RuntimeError("foreign runtime result")
    if result["survivors"] or not result["outside_unchanged"]:
        raise RuntimeError("containment cleanup failure")
    if result["artifact_b64"] is not None:
        artifact = base64.b64decode(result["artifact_b64"], validate=True)
        if (
            len(artifact) > 1048576
            or hashlib.sha256(artifact).hexdigest() != result["artifact_sha256"]
        ):
            raise RuntimeError("artifact verification failed")
    result["interrupted"] = interrupted
    result["guest_source_sha256"] = hashlib.sha256(source).hexdigest()
    result["model"] = None
    result["provider"] = None
    return result


def run_model_task(*args, **kwargs):
    raise RuntimeError("OAUTH_BROKER_UNQUALIFIED: model execution closed")


if __name__ == "__main__":
    request = json.loads(sys.stdin.buffer.read(100001))
    if set(request) != {"code", "timeout", "token"}:
        raise ValueError("exact command interface required")
    result = run_command(**request)
    print(json.dumps(result, sort_keys=True))
    sys.exit(
        0
        if result["exit_code"] == 0
        and not result["timed_out"]
        and not result["interrupted"]
        else 2
    )
