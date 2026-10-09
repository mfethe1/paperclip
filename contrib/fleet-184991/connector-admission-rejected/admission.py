"""Read-only Hermes authentication admission; never dispatches a model run."""
import ipaddress
import json
import secrets
import ssl
import urllib.error
import urllib.parse
import urllib.request


class AdmissionError(RuntimeError):
    """Sanitized, fail-closed admission refusal."""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def endpoint(base_url):
    parsed = urllib.parse.urlsplit(base_url)
    if (parsed.username or parsed.password or parsed.query or parsed.fragment
            or not parsed.hostname or parsed.scheme not in {"http", "https"}):
        raise AdmissionError("invalid_endpoint")
    try:
        parsed.port
    except ValueError:
        raise AdmissionError("invalid_endpoint") from None
    try:
        loopback = ipaddress.ip_address(parsed.hostname).is_loopback
    except ValueError:
        loopback = False
    if parsed.scheme == "http" and not loopback:
        raise AdmissionError("remote_plain_http_denied")
    if "%" in parsed.path or "\\" in parsed.path or any(
            segment in {".", ".."} for segment in parsed.path.split("/")):
        raise AdmissionError("ambiguous_endpoint_path")
    return base_url.rstrip("/") + "/v1/models"


def admit(base_url, token, *, timeout=5, context=None):
    """Use a caller-resolved connector-only key; return no secret or response body.

    A passing result is authentication admission only, never execution acceptance.
    The caller must bind the endpoint to the intended host and validate run receipts.
    """
    url = endpoint(base_url)
    if not isinstance(token, str) or not 16 <= len(token) <= 4096 or any(
            ord(c) < 33 or ord(c) > 126 for c in token):
        raise AdmissionError("invalid_connector_credential")
    if not isinstance(timeout, (int, float)) or not 0 < timeout <= 30:
        raise AdmissionError("invalid_timeout")
    tls = context or ssl.create_default_context()
    if tls.verify_mode != ssl.CERT_REQUIRED or not tls.check_hostname:
        raise AdmissionError("tls_verification_required")
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}), NoRedirect(),
        urllib.request.HTTPSHandler(context=tls))

    def fetch(credential):
        headers = {} if credential is None else {"Authorization": "Bearer " + credential}
        request = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with opener.open(request, timeout=timeout) as response:
                body = response.read(32769)
                if len(body) > 32768:
                    raise AdmissionError("response_too_large")
                return response.status, body
        except urllib.error.HTTPError as exc:
            status = exc.code
            exc.close()
            return status, b""
        except (urllib.error.URLError, OSError, ValueError):
            raise AdmissionError("transport_rejected") from None

    # Negative admission comes first: public health is never consulted.
    missing, _ = fetch(None)
    if missing != 401:
        raise AdmissionError("missing_credential_not_rejected")
    wrong = secrets.token_urlsafe(32)
    while wrong == token:
        wrong = secrets.token_urlsafe(32)
    invalid, _ = fetch(wrong)
    if invalid != 401:
        raise AdmissionError("wrong_credential_not_rejected")
    valid, body = fetch(token)
    if valid != 200:
        raise AdmissionError("credential_not_accepted")
    try:
        data = json.loads(body)
    except (ValueError, UnicodeError):
        raise AdmissionError("invalid_models_response") from None
    if (not isinstance(data, dict) or data.get("object") != "list"
            or not isinstance(data.get("data"), list) or not data["data"]
            or any(not isinstance(m, dict) or not isinstance(m.get("id"), str)
                   or not m["id"] for m in data["data"])):
        raise AdmissionError("invalid_models_response")
    return {"endpoint": url, "valid_status": valid, "missing_status": missing,
            "wrong_status": invalid, "model_count": len(data["data"]),
            "tls_verified": url.startswith("https://"),
            "authentication_admitted": True, "execution_qualified": False}
