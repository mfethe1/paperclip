"""Canonical candidate verification. Uses installed tools only, no package installs."""

import ast
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
EVIDENCE = ROOT / "evidence"
EVIDENCE.mkdir(exist_ok=True)


def run(label, command):
    result = subprocess.run(
        command, cwd=ROOT, capture_output=True, text=True, timeout=60, check=False
    )
    (EVIDENCE / (label + ".log")).write_text(
        "command="
        + json.dumps(command)
        + "\nexit_code="
        + str(result.returncode)
        + "\n"
        + result.stdout
        + result.stderr
    )
    print(label, "exit", result.returncode)
    return result


def main():
    test = run("tests", [sys.executable, "-m", "unittest", "discover", "-v"])
    if test.returncode:
        raise SystemExit(1)
    count = int(re.search(r"Ran (\d+) tests", test.stderr)[1])
    ruff = shutil.which("ruff")
    if not ruff:
        raise SystemExit("installed ruff unavailable; no installs allowed")
    lint = run(
        "lint",
        [ruff, "check", "--isolated", "--select", "E4,E7,E9,F,I,BLE,PLW1510", "."],
    )
    if lint.returncode:
        raise SystemExit(1)
    for path in ROOT.glob("*.py"):
        ast.parse(path.read_text(), filename=str(path))
    scoped = run("scoped-os-probe", [sys.executable, "probe_runner.py", "--scoped"])
    scoped_data = json.loads(scoped.stdout)
    probes = json.loads(scoped_data["stdout"])
    denied = [
        "outside_read",
        "outside_write",
        "symlink_read",
        "network",
        "socket",
        "nested_dispatch_read",
    ]
    if (
        scoped_data["exit_code"] != 0
        or not scoped_data["host_witness_unchanged"]
        or not scoped_data["artifact_sha256"]
        or scoped_data["output_limit_exceeded"]
        or not probes["positive_write"]
        or not probes["environment_clean"]
        or not all(probes[name]["denied"] for name in denied)
    ):
        raise SystemExit("actual OS deny-witness probe failed; see evidence")
    strict = run("strict-os-probe", [sys.executable, "probe_runner.py"])
    strict_data = json.loads(strict.stdout)
    summary = {
        "verified_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "unit_and_local_integration_tests": count,
        "lint": "passed",
        "syntax": "passed",
        "actual_scoped_os_denials": denied,
        "strict_profile_exit_code": strict_data["exit_code"],
        "execution_enabled": False,
        "fleet_acceptance": False,
        "strict_typecheck": "not run: mypy unavailable; no package installation authorized",
    }
    (EVIDENCE / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
