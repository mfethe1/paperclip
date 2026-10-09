"""Real HTTP and certificate-validated TLS client acceptance tests."""
import contextlib
import http.server
import json
import os
from pathlib import Path
import ssl
import subprocess
import tempfile
import threading
import unittest

from admission import AdmissionError, admit, endpoint

TOKEN = "test-only-connector-key-184991"


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        self.server.requests.append((self.path, self.headers.get("Authorization")))
        mode = self.server.mode
        authorized = self.headers.get("Authorization") == "Bearer " + TOKEN
        if self.path == "/health":
            code, body = 200, b'{"status":"ok"}'
        elif mode == "health_only":
            code, body = 404, b""
        elif mode == "redirect":
            self.send_response(302)
            self.send_header("Location", self.server.redirect)
            self.end_headers()
            return
        elif mode == "open":
            code, body = 200, b"{}"
        elif not authorized:
            code, body = 401, b""
        else:
            code = 200
            body = json.dumps({"object": "list", "data": [{"id": "test-model"}]}).encode()
            if mode == "invalid_json":
                body = b"not json"
            elif mode == "empty":
                body = b'{"object":"list","data":[]}'
            elif mode == "huge":
                body = b"x" * 32769
        self.send_response(code)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@contextlib.contextmanager
def server(mode="secure", tls=None, redirect=""):
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    srv.requests, srv.mode, srv.redirect = [], mode, redirect
    if tls:
        srv.socket = tls.wrap_socket(srv.socket, server_side=True)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield srv, ("https" if tls else "http") + "://127.0.0.1:" + str(srv.server_port)
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=2)


class AdmissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR"))
        root = Path(cls.temp.name)
        cert, key = root / "cert.pem", root / "key.pem"
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
                        "-keyout", str(key), "-out", str(cert), "-days", "1",
                        "-subj", "/CN=localhost", "-addext",
                        "subjectAltName=IP:127.0.0.1"], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cls.tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        cls.tls.load_cert_chain(cert, key)
        cls.trust = ssl.create_default_context(cafile=str(cert))

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_real_http_auth_and_bounded_report(self):
        with server() as (srv, base):
            result = admit(base, TOKEN)
            self.assertEqual([result[k] for k in ("missing_status", "wrong_status", "valid_status")],
                             [401, 401, 200])
            self.assertFalse(result["execution_qualified"])
            self.assertNotIn(TOKEN, json.dumps(result))
            self.assertEqual(len(srv.requests), 3)
            self.assertTrue(all(p == "/v1/models" for p, _ in srv.requests))

    def test_real_tls_auth_and_host_verification(self):
        with server(tls=self.tls) as (_, base):
            self.assertTrue(admit(base, TOKEN, context=self.trust)["tls_verified"])

    def test_untrusted_certificate_rejected(self):
        with server(tls=self.tls) as (_, base):
            with self.assertRaisesRegex(AdmissionError, "transport_rejected"):
                admit(base, TOKEN)

    def test_disabled_tls_verification_rejected(self):
        with self.assertRaisesRegex(AdmissionError, "tls_verification_required"):
            admit("https://127.0.0.1:1", TOKEN, context=ssl._create_unverified_context())

    def test_wrong_connector_key_denied(self):
        with server() as (_, base):
            with self.assertRaisesRegex(AdmissionError, "credential_not_accepted"):
                admit(base, "wrong-test-connector-key")

    def test_public_health_cannot_pass(self):
        with server("health_only") as (srv, base):
            with self.assertRaisesRegex(AdmissionError, "missing_credential_not_rejected"):
                admit(base, TOKEN)
            self.assertNotIn("/health", [p for p, _ in srv.requests])

    def test_open_endpoint_cannot_pass(self):
        with server("open") as (_, base):
            with self.assertRaisesRegex(AdmissionError, "missing_credential_not_rejected"):
                admit(base, TOKEN)

    def test_redirect_never_followed(self):
        with server() as (target, target_url):
            with server("redirect", redirect=target_url + "/v1/models") as (_, base):
                with self.assertRaises(AdmissionError):
                    admit(base, TOKEN)
            self.assertEqual(target.requests, [])

    def test_response_shape_and_bounds(self):
        for mode in ["invalid_json", "empty", "huge"]:
            with self.subTest(mode=mode), server(mode) as (_, base):
                with self.assertRaises(AdmissionError):
                    admit(base, TOKEN)

    def test_invalid_endpoints_and_credentials(self):
        for url in ["http://example.com", "https://u:p@example.com", "https://example.com?a=b",
                    "https://example.com#token", "https://example.com/../", "https://example.com/%2f",
                    "https://example.com:bad", "ftp://example.com"]:
            with self.subTest(url=url), self.assertRaises(AdmissionError):
                endpoint(url)
        for token in ["", "short", "x" * 16 + "\r\n", None]:
            with self.subTest(token=token), self.assertRaises(AdmissionError):
                admit("http://127.0.0.1:1", token)


if __name__ == "__main__":
    unittest.main()
