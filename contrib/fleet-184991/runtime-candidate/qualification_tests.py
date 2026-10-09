import base64
import json
import os
import signal
import subprocess
import sys
import time
import unittest
import uuid
from pathlib import Path

import runtime

EVIDENCE = Path(__file__).parent / "evidence"
EVIDENCE.mkdir(exist_ok=True)


class RuntimeTests(unittest.TestCase):
    def record(self, name, result):
        (EVIDENCE / (name + ".json")).write_text(json.dumps(result, indent=2))

    def test_real_artifact_and_denials(self):
        os.environ["PAPERCLIP_API_KEY"] = "SYNTHETIC-MUST-NOT-ENTER"
        try:
            code = r"""
import json,os,pathlib,socket,subprocess
r={}
w=pathlib.Path('/workspace')
# Useful real command: calculate, compile and run task-local source.
source='def square(x): return x*x'
(w/'program.py').write_text(source)
exec(compile(source,'program.py','exec'))
(w/'artifact.txt').write_text(str(square(7)))
r['positive_artifact']=(w/'artifact.txt').read_text()=='49'
def denied(name, fn, expected):
 try: fn(); r[name]={'denied':False}
 except OSError as e: r[name]={'denied':e.errno in expected,'errno':e.errno}
denied('outside_read',lambda:pathlib.Path('/outside/outside.txt').read_text(),{13})
denied('outside_write',lambda:pathlib.Path('/outside/changed').write_text('BAD'),{30})
denied('readonly_runtime_write',lambda:pathlib.Path('/usr/changed').write_text('BAD'),{30})
denied('symlink_escape',lambda:(w/'escape').read_text(),{13})
denied('network',lambda:socket.socket(socket.AF_INET),{1})
denied('existing_control_socket',lambda:socket.socket(socket.AF_UNIX).connect('/outside/control.sock'),{1})
r['environment_clean']='PAPERCLIP_API_KEY' not in os.environ and 'OPENAI_API_KEY' not in os.environ
r['host_home_absent']=not pathlib.Path('/home/operator').exists()  # sanitized: original asserted operator host home absent
r['guest_home_absent']=not pathlib.Path('/var/home/core').exists()
r['oauth_files_absent']=not pathlib.Path('/home/operator/.pi/agent/auth.json').exists()  # sanitized
r['host_socket_absent']=not pathlib.Path('/run/podman/podman.sock').exists()
denied('nested_host_dispatch',lambda:subprocess.run(['/home/operator/.config/hermes-fleet/fleet-dispatch.py','ask','anything'],check=True)  # sanitized,{2})
denied('nested_network_dispatch',lambda:socket.socket(socket.AF_INET).connect(('192.0.2.10',11434))  # sanitized: RFC5737 placeholder for private inference host,{1})
r['capabilities_zero']=next(x for x in pathlib.Path('/proc/self/status').read_text().splitlines() if x.startswith('CapEff:')).split()[1]=='0000000000000000'
print(json.dumps(r,sort_keys=True))
"""
            result = runtime.run_command(code)
        finally:
            del os.environ["PAPERCLIP_API_KEY"]
        self.record("denials", result)
        self.assertEqual(result["exit_code"], 0, result)
        checks = json.loads(result["stdout"])
        for name, value in checks.items():
            self.assertTrue(value["denied"] if isinstance(value, dict) else value, name)
        self.assertTrue(result["outside_unchanged"])
        self.assertTrue(result["socket_control_connected"])
        self.assertEqual(base64.b64decode(result["artifact_b64"]), b"49")

    def test_timeout_kills_setsid_child(self):
        token = str(uuid.uuid4())
        code = """import os,time,sys
p=os.fork()
if p==0:
 os.setsid()
 print('escaped-child-started',flush=True)
 while True: time.sleep(1)
print('parent-started',flush=True)
while True: time.sleep(1)
"""
        result = runtime.run_command(code, timeout=2, token=token)
        self.record("timeout-escaped-child", result)
        self.assertTrue(result["timed_out"])
        self.assertIn("escaped-child-started", result["stdout"])
        self.assertEqual(result["survivors"], [])
        self.assert_guest_token_gone(token)

    def assert_guest_token_gone(self, token):
        source = """import pathlib,sys
needle=sys.argv[1].encode()
found=[]
for p in pathlib.Path('/proc').iterdir():
 if p.name.isdigit():
  try:
   c=(p/'cmdline').read_bytes()
   if needle in c and (b'python3\\0-I\\0-c' in c or b'bwrap\\0' in c): found.append(p.name)
  except OSError: pass
print(found)
assert not found
"""
        import shlex

        child = runtime.transport(
            "/usr/bin/python3 -c " + shlex.quote(source) + " " + token,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        out, err = child.communicate(timeout=5)
        self.assertEqual(child.returncode, 0, (out, err))

    def test_host_interruption_cleans_escaped_child(self):
        token = str(uuid.uuid4())
        code = """import os,time
p=os.fork()
if p==0:
 os.setsid()
 print('escaped-child-started',flush=True)
 while True: time.sleep(1)
while True: time.sleep(1)
"""
        proc = subprocess.Popen(
            [sys.executable, str(Path(runtime.__file__))],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        assert proc.stdin is not None
        proc.stdin.write(
            json.dumps({"code": code, "timeout": 10, "token": token}).encode()
        )
        proc.stdin.close()
        proc.stdin = None
        # Read task-owned state instead of relying on a blind sleep.
        import shlex

        ready_code = "import pathlib,sys,time; p=pathlib.Path('/var/home/core'); token=sys.argv[1]; end=time.time()+5\nwhile time.time()<end:\n ds=list(p.glob('pc-runtime-'+token+'-*'))\n if ds and (ds[0]/'pid').exists(): break\n time.sleep(.05)\nelse: raise RuntimeError('worker did not start')\nprint('ready')"
        ready = runtime.transport(
            "/usr/bin/python3 -c " + shlex.quote(ready_code) + " " + token,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        out, err = ready.communicate(timeout=8)
        self.assertEqual(ready.returncode, 0, (out, err))
        time.sleep(0.3)
        proc.send_signal(signal.SIGTERM)
        out, err = proc.communicate(timeout=10)
        self.assertEqual(proc.returncode, 2, (out, err))
        result = json.loads(out)
        self.record("interruption", result)
        self.assertTrue(result["interrupted"])
        self.assertIn("escaped-child-started", result["stdout"])
        self.assertEqual(result["survivors"], [])
        self.assert_guest_token_gone(token)

    def test_model_remains_closed(self):
        with self.assertRaisesRegex(RuntimeError, "OAUTH_BROKER_UNQUALIFIED"):
            runtime.run_model_task(model=runtime.MODEL, provider=runtime.PROVIDER)
        for timeout in (True, 0, 11):
            with self.assertRaises(ValueError):
                runtime.run_command("print(1)", timeout=timeout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
