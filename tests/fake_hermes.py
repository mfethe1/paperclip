#!/usr/bin/env python3
"""A stand-in for a Hermes API server, for testing the Paperclip <-> Hermes loop.

Speaks the subset of the API the hermes_gateway adapter uses:
  GET  /health                 open
  GET  /v1/capabilities        needs the key
  POST /v1/runs                needs the key; starts a run
  GET  /v1/runs/{id}           run status (the adapter polls this)
  GET  /v1/runs/{id}/events    404, so the adapter falls back to polling
  POST /v1/runs/{id}/stop

For each run it does what a real Hermes would do with the paperclip-fleet skill: it
reads the Run ID and the issue key from the wake prompt and closes the issue with
hermes/skills/paperclip-fleet/scripts/paperclip-issue-update.sh, using the
PAPERCLIP_* values in $HERMES_HOME/.env. The prompt is saved to
$HERMES_HOME/last-input.txt for inspection.

Usage: FAKE_HERMES_KEY=... HERMES_HOME=... fake_hermes.py --port 18643
"""
from __future__ import annotations

import argparse
import http.server
import json
import os
import re
import subprocess
import threading
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "hermes" / "skills" / "paperclip-fleet" / "scripts" / "paperclip-issue-update.sh"
RUNS: dict[str, dict] = {}
LOCK = threading.Lock()


def hermes_env() -> dict[str, str]:
    env = dict(os.environ)
    path = Path(os.environ["HERMES_HOME"]) / ".env"
    for line in path.read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


def work(run_id: str, prompt: str) -> None:
    (Path(os.environ["HERMES_HOME"]) / "last-input.txt").write_text(prompt)
    pc_run = re.search(r"Run ID:\s*([0-9a-f-]{36})", prompt)
    issue = re.search(r"\b([A-Z][A-Z0-9]*-\d+)\b", prompt)
    if not (pc_run and issue):
        result = {"status": "failed", "error": "no Run ID or issue key in the wake prompt"}
    else:
        p = subprocess.run(
            ["bash", str(HELPER), "--issue-id", issue.group(1), "--status", "done", "--run-id", pc_run.group(1), "--comment", "-"],
            input="DID:  fake Hermes closed this from a Paperclip wake\nNEXT: nothing\nNEED: nothing\n",
            capture_output=True, text=True, env=hermes_env(), timeout=120)
        if p.returncode == 0:
            result = {"status": "completed", "output": p.stdout.strip()}
        else:
            result = {"status": "failed", "error": (p.stderr or p.stdout).strip()[:500]}
    with LOCK:
        RUNS[run_id].update(result)


class Handler(http.server.BaseHTTPRequestHandler):
    def _send(self, code: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _authed(self) -> bool:
        return self.headers.get("authorization") == f"Bearer {os.environ['FAKE_HERMES_KEY']}"

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            return self._send(200, {"status": "ok", "platform": "hermes-agent", "version": "fake"})
        if not self._authed():
            return self._send(401, {"error": "unauthorized"})
        if self.path == "/v1/capabilities":
            return self._send(200, {"capabilities": ["runs"]})
        m = re.fullmatch(r"/v1/runs/([^/]+)", self.path)
        if m and m.group(1) in RUNS:
            with LOCK:
                return self._send(200, dict(RUNS[m.group(1)]))
        return self._send(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if not self._authed():
            return self._send(401, {"error": "unauthorized"})
        length = int(self.headers.get("content-length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        if self.path == "/v1/runs":
            run_id = f"run_{uuid.uuid4().hex[:12]}"
            with LOCK:
                RUNS[run_id] = {"run_id": run_id, "status": "running"}
            threading.Thread(target=work, args=(run_id, str(body.get("input") or "")), daemon=True).start()
            return self._send(202, {"run_id": run_id, "status": "running"})
        m = re.fullmatch(r"/v1/runs/([^/]+)/stop", self.path)
        if m and m.group(1) in RUNS:
            with LOCK:
                RUNS[m.group(1)]["status"] = "stopped"
            return self._send(200, {"run_id": m.group(1), "status": "stopped"})
        return self._send(404, {"error": "not found"})

    def log_message(self, *args) -> None:
        pass


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=18643)
    args = ap.parse_args()
    http.server.ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
