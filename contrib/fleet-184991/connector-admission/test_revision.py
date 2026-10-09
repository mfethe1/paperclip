"""Additive real-socket regressions for URL and secret-safe HTTP failures."""
import contextlib
import http.server
import json
import threading
import traceback
import unittest

import test_admission as shipped
from admission import AdmissionError, admit, endpoint
from test_admission import TOKEN, server

MARKER = "synthetic-response-secret-184991"


class FaultHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        auth = self.headers.get("Authorization")
        authorized = auth == "Bearer " + TOKEN
        self.server.events.append((self.path, auth is not None, authorized))
        if not authorized and len(self.server.events) != self.server.fault_at:
            self.send_response(401)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        mode = self.server.mode
        body = json.dumps({"object": "list", "data": [{"id": TOKEN}], "echo": MARKER}).encode()
        prefix = b"HTTP/1.1 200 OK\r\n"
        secret = (TOKEN + MARKER).encode()
        if mode == "status":
            wire = b"HTTP_BROKEN_" + secret + b"\r\n\r\n"
        elif mode == "header":
            wire = prefix + b"X-Secret: " + secret + b"x" * 65537 + b"\r\n\r\n"
        elif mode == "headers":
            wire = prefix + (b"X-Secret: " + secret + b"\r\n") * 101 + b"\r\n"
        elif mode == "chunk":
            wire = prefix + b"Transfer-Encoding: chunked\r\n\r\n1000\r\n" + secret
        elif mode == "length":
            wire = prefix + b"Content-Length: 30000\r\n\r\n" + body
        else:
            if mode == "json":
                body = b"not-json-" + secret
            elif mode == "utf8":
                body = b"\xff" + secret
            elif mode == "deep":
                body = b"[" * 2000 + b"0" + b"]" * 2000
            wire = prefix + b"Content-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body
        self.wfile.write(wire)
        self.wfile.flush()
        self.close_connection = True


@contextlib.contextmanager
def fault_server(mode, tls=None, fault_at=3):
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), FaultHandler)
    srv.events, srv.mode, srv.fault_at = [], mode, fault_at
    if tls:
        srv.socket = tls.wrap_socket(srv.socket, server_side=True)
    thread = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
    thread.start()
    try:
        yield srv, ("https" if tls else "http") + "://127.0.0.1:" + str(srv.server_port)
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(2)


class RevisionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        shipped.AdmissionTests.setUpClass()
        cls.tls, cls.trust = shipped.AdmissionTests.tls, shipped.AdmissionTests.trust

    @classmethod
    def tearDownClass(cls):
        shipped.AdmissionTests.tearDownClass()

    def sanitized_refusal(self, base, **kwargs):
        try:
            admit(base, TOKEN, timeout=1, **kwargs)
        except AdmissionError as exc:
            formatted = "".join(traceback.format_exception(exc))
            self.assertNotIn(TOKEN, formatted)
            self.assertNotIn(MARKER, formatted)
            self.assertIsNone(exc.__cause__)
            return str(exc)
        self.fail("Expected sanitized refusal")

    def test_raw_delimiters_controls_refuse_before_socket(self):
        with server() as (srv, base):
            for suffix in ("?", "#", "/prefix?", "/prefix#", "/x\r\ny", "/x\ty",
                           "/x y", "/x\x00y", "/x\x7fy", "/x\u00e9", "//prefix",
                           "/../prefix", "/%2f", "/x\\y", "/x;y", "/" + TOKEN + "\r\n"):
                with self.subTest(suffix=suffix):
                    self.sanitized_refusal(base + suffix)
            for prefix in (" ", "\x00", "\n", "\t"):
                with self.subTest(prefix=prefix):
                    self.sanitized_refusal(prefix + base)
            self.assertEqual(srv.requests, [])

    def test_malformed_url_types_authorities_and_ports_sanitized(self):
        for url in (None, b"https://host", 1, {}, "https://[broken", "https://@host",
                    "https://user@host", "https://host:", "https://host:bad",
                    "https://host:0", "https://host:65536", "https://[::1]evil",
                    "https://-host", "https://host..invalid", "https://h\\evil.invalid",
                    "http://localhost", "http://127.1", "http://2130706433"):
            with self.subTest(url=url), self.assertRaises(AdmissionError):
                endpoint(url)

    def test_pinned_tailnet_and_ipv6_prefix_construction(self):
        self.assertEqual(endpoint("https://host.tailnet.ts.net:443/connector/"),
                         "https://host.tailnet.ts.net:443/connector/v1/models")
        self.assertEqual(endpoint("http://[::1]:8080/prefix"), "http://[::1]:8080/prefix/v1/models")

    def test_real_verified_tls_prefix_sequence_and_metadata(self):
        with fault_server("echo", tls=self.tls) as (srv, base):
            result = admit(base + "/connector/", TOKEN, context=self.trust)
            self.assertEqual([e[2] for e in srv.events], [False, False, True])
            self.assertEqual([e[1] for e in srv.events], [False, True, True])
            self.assertEqual([e[0] for e in srv.events], ["/connector/v1/models"] * 3)
            self.assertEqual(result["model_count"], 1)
            self.assertTrue(result["tls_verified"])
            self.assertFalse(result["execution_qualified"])
            self.assertNotIn(TOKEN, json.dumps(result))
            self.assertNotIn(MARKER, json.dumps(result))

    def test_secret_bearing_endpoint_refuses_without_socket(self):
        with server() as (srv, base):
            self.assertEqual(self.sanitized_refusal(base + "/" + TOKEN), "secret_endpoint_denied")
            self.assertEqual(srv.requests, [])

    def test_verified_tls_transport_failures_sanitized(self):
        for mode in ("status", "header", "headers", "chunk", "length"):
            with self.subTest(mode=mode), fault_server(mode, tls=self.tls) as (srv, base):
                self.assertEqual(self.sanitized_refusal(base, context=self.trust), "transport_rejected")
                self.assertEqual([e[2] for e in srv.events], [False, False, True])
                self.assertTrue(all(e[0] == "/v1/models" for e in srv.events))

    def test_real_http_malformed_models_json_sanitized(self):
        for mode in ("json", "utf8", "deep"):
            with self.subTest(mode=mode), fault_server(mode) as (srv, base):
                self.assertEqual(self.sanitized_refusal(base), "invalid_models_response")
                self.assertEqual([e[2] for e in srv.events], [False, False, True])

    def test_negative_transport_failures_never_send_correct_bearer(self):
        for fault_at in (1, 2):
            with self.subTest(fault_at=fault_at), fault_server("status", fault_at=fault_at) as (srv, base):
                self.assertEqual(self.sanitized_refusal(base), "transport_rejected")
                self.assertEqual(len(srv.events), fault_at)
                self.assertFalse(any(e[2] for e in srv.events))

    def test_invalid_timeout_and_context_refuse_without_socket(self):
        with server() as (srv, base):
            for timeout in (True, 0, float("nan"), float("inf"), "1"):
                with self.subTest(timeout=timeout), self.assertRaisesRegex(AdmissionError, "invalid_timeout"):
                    admit(base, TOKEN, timeout=timeout)
            self.assertEqual(self.sanitized_refusal(base, context=object()), "tls_verification_required")
            self.assertEqual(srv.requests, [])


if __name__ == "__main__":
    unittest.main()
