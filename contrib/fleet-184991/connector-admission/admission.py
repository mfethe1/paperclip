"""Read-only connector authentication admission; never dispatches a model run."""
import http.client
import ipaddress
import json
import re
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
    """Build one unambiguous models route from validated URL components."""
    if (not isinstance(base_url, str) or not 1 <= len(base_url) <= 8192
            or any(ord(c) < 33 or ord(c) > 126 for c in base_url)
            or any(c in base_url for c in "?#%\\")):
        raise AdmissionError("invalid_endpoint")
    try:
        parsed = urllib.parse.urlsplit(base_url)
        host, port = parsed.hostname, parsed.port
    except (ValueError, TypeError, UnicodeError):
        raise AdmissionError("invalid_endpoint") from None
    if (parsed.scheme not in {"http", "https"} or not host
            or "@" in parsed.netloc or parsed.netloc.endswith(":")
            or (port is not None and not 1 <= port <= 65535)):
        raise AdmissionError("invalid_endpoint")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
        if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?", host) or any(
                not label or len(label) > 63 or label.startswith("-") or label.endswith("-")
                for label in host.split(".")) or len(host) > 253:
            raise AdmissionError("invalid_endpoint") from None
    authority = "[" + host + "]" if address and address.version == 6 else host
    if port is not None:
        authority += ":" + str(port)
    if parsed.netloc.lower() != authority:
        raise AdmissionError("invalid_endpoint")
    if parsed.scheme == "http" and not (address and address.is_loopback):
        raise AdmissionError("remote_plain_http_denied")
    path = parsed.path
    if ("//" in path or not re.fullmatch(r"(?:/[A-Za-z0-9._~-]*)*", path)
            or any(segment in {".", ".."} for segment in path.split("/"))):
        raise AdmissionError("ambiguous_endpoint_path")
    return urllib.parse.urlunsplit((parsed.scheme, authority,
                                    path.rstrip("/") + "/v1/models", "", ""))


def admit(base_url, token, *, timeout=5, context=None):
    """Authenticate only; caller must bind host identity and verify run receipts."""
    if not isinstance(token, str) or not 16 <= len(token) <= 4096 or any(
            ord(c) < 33 or ord(c) > 126 for c in token):
        raise AdmissionError("invalid_connector_credential")
    url = endpoint(base_url)
    if token in base_url or token in url:
        raise AdmissionError("secret_endpoint_denied")
    if type(timeout) not in (int, float) or not 0 < timeout <= 30:
        raise AdmissionError("invalid_timeout")
    try:
        tls = ssl.create_default_context() if context is None else context
        if (not isinstance(tls, ssl.SSLContext) or tls.verify_mode != ssl.CERT_REQUIRED
                or not tls.check_hostname):
            raise AdmissionError("tls_verification_required")
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), NoRedirect(),
            urllib.request.HTTPSHandler(context=tls))
    except (OSError, ValueError, TypeError):
        raise AdmissionError("transport_rejected") from None

    def fetch(credential):
        headers = {} if credential is None else {"Authorization": "Bearer " + credential}
        try:
            request = urllib.request.Request(url, headers=headers, method="GET")
            try:
                with opener.open(request, timeout=timeout) as response:
                    body = response.read(32769)
                    if len(body) > 32768:
                        raise AdmissionError("response_too_large")
                    if response.length is not None and response.length > 0:
                        raise AdmissionError("transport_rejected")
                    return response.status, body
            except urllib.error.HTTPError as exc:
                status = exc.code
                exc.close()
                return status, b""
        except (urllib.error.URLError, http.client.HTTPException, OSError,
                ValueError, TypeError):
            # Never stringify or chain URL, server response or transport exceptions.
            raise AdmissionError("transport_rejected") from None

    # Missing and generated wrong credentials must be denied before the caller key.
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
    except (ValueError, UnicodeError, RecursionError):
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
