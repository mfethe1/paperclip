"""Trusted VM launcher. Never installed as a service; no credentials received."""

import base64
import ctypes
import hashlib
import json
import os
import resource
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def limits():
    for kind, value in [
        (resource.RLIMIT_AS, 268435456),
        (resource.RLIMIT_CPU, 5),
        (resource.RLIMIT_FSIZE, 1048576),
        (resource.RLIMIT_NOFILE, 64),
        (resource.RLIMIT_NPROC, 64),
    ]:
        resource.setrlimit(kind, (value, value))


def seccomp_file(root):
    lib = ctypes.CDLL("libseccomp.so.2")
    lib.seccomp_init.argtypes = [ctypes.c_uint32]
    lib.seccomp_init.restype = ctypes.c_void_p
    lib.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
    lib.seccomp_syscall_resolve_name.restype = ctypes.c_int
    lib.seccomp_rule_add.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_int,
        ctypes.c_uint,
    ]
    lib.seccomp_export_bpf.argtypes = [ctypes.c_void_p, ctypes.c_int]
    lib.seccomp_release.argtypes = [ctypes.c_void_p]
    ctx = lib.seccomp_init(0x7FFF0000)
    if not ctx:
        raise RuntimeError("seccomp_init failed")
    path = root / "filter.bpf"
    try:
        # Filesystem default isolation is provided by empty mount namespace,
        # not this supplementary syscall deny list. No host root/home is bound.
        for name in [
            "socket",
            "socketpair",
            "connect",
            "bind",
            "listen",
            "accept",
            "accept4",
            "ptrace",
            "mount",
            "umount2",
            "setns",
            "unshare",
            "bpf",
            "keyctl",
            "perf_event_open",
        ]:
            num = lib.seccomp_syscall_resolve_name(name.encode())
            if num >= 0 and lib.seccomp_rule_add(ctx, 0x50001, num, 0) != 0:
                raise RuntimeError("seccomp rule failed")
        with path.open("wb") as out:
            if lib.seccomp_export_bpf(ctx, out.fileno()) != 0:
                raise RuntimeError("seccomp export failed")
    finally:
        lib.seccomp_release(ctx)
    return os.open(path, os.O_RDONLY)


def run(payload):
    token = payload["token"]
    # Host validates canonical UUID; guest validates independently.
    import uuid

    if str(uuid.UUID(token)) != token:
        raise ValueError("invalid token")
    code = base64.b64decode(payload["code"], validate=True).decode()
    if len(code.encode()) > 65536:
        raise ValueError("code too large")
    timeout = payload["timeout"]
    if not isinstance(timeout, int) or not 1 <= timeout <= 10:
        raise ValueError("invalid deadline")
    with tempfile.TemporaryDirectory(
        prefix="pc-runtime-" + token + "-", dir="/var/home/core"
    ) as temp:
        root = Path(temp)
        workspace = root / "work"
        workspace.mkdir()
        outside = root / "private"
        outside.mkdir()
        secret = outside / "outside.txt"
        secret.write_text("UNCHANGED synthetic host-owned witness")
        secret.chmod(0)
        (workspace / "escape").symlink_to("/outside/outside.txt")
        with socket.socket(socket.AF_UNIX) as control:
            control.bind(str(outside / "control.sock"))
            control.listen(1)
            # Actual existing socket control: unsandboxed connection succeeds.
            with socket.socket(socket.AF_UNIX) as check:
                check.connect(str(outside / "control.sock"))
                accepted, _ = control.accept()
                accepted.close()
            fd = seccomp_file(root)
            argv = [
                "/usr/bin/bwrap",
                "--unshare-all",
                "--die-with-parent",
                "--new-session",
                "--cap-drop",
                "ALL",
                "--ro-bind",
                "/usr",
                "/usr",
                "--symlink",
                "usr/lib64",
                "/lib64",
                "--symlink",
                "usr/lib",
                "/lib",
                "--symlink",
                "usr/bin",
                "/bin",
                "--proc",
                "/proc",
                "--dev",
                "/dev",
                "--bind",
                str(workspace),
                "/workspace",
                "--ro-bind",
                str(outside),
                "/outside",
                "--chdir",
                "/workspace",
                "--clearenv",
                "--setenv",
                "HOME",
                "/workspace",
                "--setenv",
                "PATH",
                "/usr/bin",
                "--setenv",
                "LANG",
                "C.UTF-8",
                "--seccomp",
                str(fd),
                "--",
                "/usr/bin/python3",
                "-I",
                "-c",
                code,
                token,
            ]
            out = (root / "stdout").open("w+b")
            err = (root / "stderr").open("w+b")
            child = None
            timed_out = False
            try:
                limits()  # Single-threaded disposable launcher; inherited by child.
                child = subprocess.Popen(
                    argv,
                    stdin=subprocess.DEVNULL,
                    stdout=out,
                    stderr=err,
                    pass_fds=(fd,),
                    start_new_session=True,
                )
                (root / "pid").write_text(str(child.pid))
                try:
                    child.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    timed_out = True
                finally:
                    # Killing bwrap's namespace supervisor destroys every PID,
                    # including a child that called setsid or double-forked.
                    try:
                        os.killpg(child.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    child.wait(timeout=3)
                time.sleep(0.15)
                survivors = []
                for proc in Path("/proc").iterdir():
                    if proc.name.isdigit():
                        try:
                            cmd = (proc / "cmdline").read_bytes()
                            if token.encode() in cmd and (
                                b"python3\x00-I\x00-c" in cmd or b"bwrap\x00" in cmd
                            ):
                                survivors.append(int(proc.name))
                        except OSError:
                            pass
                resource_limits = {
                    "per_process_address_space": 268435456,
                    "per_process_cpu_seconds": 5,
                    "uid_processes": 64,
                    "file_bytes": 1048576,
                    "aggregate_cgroup_enforced": False,
                }
                out.seek(0)
                err.seek(0)
                artifact = workspace / "artifact.txt"
                artifact_bytes = None
                if artifact.exists() and not artifact.is_symlink():
                    st = artifact.stat()
                    if (
                        artifact.is_file()
                        and st.st_nlink == 1
                        and st.st_size <= 1048576
                    ):
                        artifact_bytes = artifact.read_bytes()
                secret.chmod(0o600)
                return {
                    "runtime": "podman-vm-bwrap-v1",
                    "token": token,
                    "exit_code": child.returncode,
                    "timed_out": timed_out,
                    "stdout": out.read(65537).decode(errors="replace"),
                    "stderr": err.read(65537).decode(errors="replace"),
                    "survivors": survivors,
                    "resource_limits": resource_limits,
                    "outside_unchanged": secret.read_text()
                    == "UNCHANGED synthetic host-owned witness",
                    "socket_control_connected": True,
                    "artifact_b64": base64.b64encode(artifact_bytes).decode()
                    if artifact_bytes is not None
                    else None,
                    "artifact_sha256": hashlib.sha256(artifact_bytes).hexdigest()
                    if artifact_bytes is not None
                    else None,
                }
            finally:
                os.close(fd)
                out.close()
                err.close()


if __name__ == "__main__":
    # Payload appended by the fixed host runner, not obtained from guest files.
    print(json.dumps(run(json.loads(sys.argv[1])), sort_keys=True))
