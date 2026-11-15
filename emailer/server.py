"""Minimal same-origin web server for the emailer UI and API."""

import hashlib
import json
import logging
import re
import threading
import time
from collections import defaultdict, deque
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from typing import Callable
from urllib.parse import urlsplit

from .mailer import MailDeliveryError, SendResult, send_email
from .models import MailRequest, ValidationError
from .providers import public_providers


LOGGER = logging.getLogger("emailer.server")
MAX_REQUEST_BYTES = 18 * 1024 * 1024
IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{15,127}$")

STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/sw.js": ("sw.js", "text/javascript; charset=utf-8"),
    "/manifest.webmanifest": ("manifest.webmanifest", "application/manifest+json"),
    "/icon.svg": ("icon.svg", "image/svg+xml"),
}


class RateLimiter:
    def __init__(self, limit: int = 10, window_seconds: int = 60) -> None:
        if limit < 1 or window_seconds < 1:
            raise ValueError("rate limit and window must be positive")
        self.limit = limit
        self.window_seconds = window_seconds
        self._events: defaultdict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()
        self._last_cleanup = time.monotonic()

    def allow(self, key: str) -> tuple[bool, int]:
        now = time.monotonic()
        cutoff = now - self.window_seconds
        with self._lock:
            if now - self._last_cleanup >= self.window_seconds:
                for event_key, event_times in tuple(self._events.items()):
                    while event_times and event_times[0] <= cutoff:
                        event_times.popleft()
                    if not event_times:
                        del self._events[event_key]
                self._last_cleanup = now
            events = self._events[key]
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= self.limit:
                retry_after = max(1, int(self.window_seconds - (now - events[0])) + 1)
                return False, retry_after
            events.append(now)
            return True, 0


class IdempotencyStore:
    def __init__(self, ttl_seconds: int = 600, max_entries: int = 1_000) -> None:
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self._records: dict[str, dict[str, object]] = {}
        self._lock = threading.Lock()

    def begin(
        self, key: str, fingerprint: str
    ) -> tuple[str, tuple[HTTPStatus, dict[str, object]] | None]:
        now = time.monotonic()
        with self._lock:
            self._prune(now)
            record = self._records.get(key)
            if record is not None:
                if record["fingerprint"] != fingerprint:
                    return "conflict", None
                response = record.get("response")
                if response is None:
                    return "in_progress", None
                return "complete", response  # type: ignore[return-value]
            if len(self._records) >= self.max_entries:
                oldest_key = min(self._records, key=lambda item: float(self._records[item]["created"]))
                del self._records[oldest_key]
            self._records[key] = {
                "fingerprint": fingerprint,
                "created": now,
                "response": None,
            }
            return "new", None

    def complete(
        self,
        key: str,
        fingerprint: str,
        status: HTTPStatus,
        payload: dict[str, object],
    ) -> None:
        with self._lock:
            record = self._records.get(key)
            if record is not None and record["fingerprint"] == fingerprint:
                record["response"] = (status, payload)

    def discard(self, key: str, fingerprint: str) -> None:
        with self._lock:
            record = self._records.get(key)
            if record is not None and record["fingerprint"] == fingerprint:
                del self._records[key]

    def _prune(self, now: float) -> None:
        cutoff = now - self.ttl_seconds
        for key, record in tuple(self._records.items()):
            if float(record["created"]) <= cutoff:
                del self._records[key]


class EmailerHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        server_address: tuple[str, int],
        *,
        send_func: Callable[[MailRequest], SendResult] = send_email,
        rate_limit: int = 10,
    ) -> None:
        if server_address[0].casefold().rstrip(".") not in {"localhost", "127.0.0.1"}:
            raise ValueError("Simple Emailer only accepts loopback bindings")
        self.send_func = send_func
        self.rate_limiter = RateLimiter(limit=rate_limit)
        self.idempotency = IdempotencyStore()
        super().__init__(server_address, EmailerRequestHandler)


class EmailerRequestHandler(BaseHTTPRequestHandler):
    server: EmailerHTTPServer
    server_version = "SimpleEmailer"
    sys_version = ""

    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(15)

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if not self._valid_host():
            self._send_error(HTTPStatus.FORBIDDEN, "invalid_host", "Request host is not allowed.")
            return
        if path == "/api/health":
            self._send_json(HTTPStatus.OK, {"ok": True, "service": "simple-emailer"})
            return
        if path == "/api/providers":
            self._send_json(HTTPStatus.OK, {"providers": public_providers()})
            return
        static_file = STATIC_FILES.get(path)
        if static_file is None:
            self._send_error(HTTPStatus.NOT_FOUND, "not_found", "The requested page was not found.")
            return
        filename, content_type = static_file
        try:
            content = resources.files("emailer.static").joinpath(filename).read_bytes()
        except (FileNotFoundError, OSError):
            self._send_error(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                "asset_missing",
                "An application asset is missing.",
            )
            return
        self.send_response(HTTPStatus.OK)
        self._security_headers()
        self.send_header("Content-Type", content_type)
        self.send_header(
            "Cache-Control",
            "no-cache" if path in {"/", "/index.html", "/sw.js"} else "public, max-age=3600",
        )
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_POST(self) -> None:
        path = urlsplit(self.path).path
        if path != "/api/send":
            self._send_error(HTTPStatus.NOT_FOUND, "not_found", "The requested endpoint was not found.")
            return
        if not self._valid_host() or not self._valid_origin():
            self._send_error(HTTPStatus.FORBIDDEN, "origin_rejected", "Request origin is not allowed.")
            return
        if self.headers.get("X-Emailer-Request") != "send-message":
            self._send_error(HTTPStatus.FORBIDDEN, "request_rejected", "Required request header is missing.")
            return
        idempotency_key = self.headers.get("Idempotency-Key", "")
        if not IDEMPOTENCY_KEY.fullmatch(idempotency_key):
            self._send_error(
                HTTPStatus.BAD_REQUEST,
                "idempotency_key",
                "A valid idempotency key is required.",
            )
            return
        media_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if media_type != "application/json":
            self._send_error(
                HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
                "content_type",
                "Use application/json for this endpoint.",
            )
            return

        try:
            content_length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            content_length = -1
        if content_length < 0:
            self._send_error(HTTPStatus.LENGTH_REQUIRED, "length_required", "Content-Length is required.")
            return
        if content_length > MAX_REQUEST_BYTES:
            self._send_error(
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                "request_too_large",
                "The request is too large.",
            )
            return

        raw_body = self.rfile.read(content_length)
        try:
            payload = json.loads(raw_body)
        except (ValueError, UnicodeDecodeError, RecursionError):
            self._send_error(HTTPStatus.BAD_REQUEST, "invalid_json", "The request is not valid JSON.")
            return

        try:
            fingerprint = _payload_fingerprint(payload)
        except (TypeError, ValueError, RecursionError):
            if isinstance(payload, dict):
                payload["app_password"] = None
            self._send_error(HTTPStatus.BAD_REQUEST, "invalid_json", "The request is not valid JSON.")
            return
        idempotency_state, cached_response = self.server.idempotency.begin(
            idempotency_key, fingerprint
        )
        if idempotency_state == "conflict":
            self._send_error(
                HTTPStatus.CONFLICT,
                "idempotency_conflict",
                "This send identifier was already used for a different message.",
            )
            return
        if idempotency_state == "in_progress":
            self._send_error(
                HTTPStatus.CONFLICT,
                "send_in_progress",
                "This message is still being processed. Wait before checking again.",
            )
            return
        if idempotency_state == "complete" and cached_response is not None:
            cached_status, cached_payload = cached_response
            self._send_json(cached_status, cached_payload)
            return

        allowed, retry_after = self.server.rate_limiter.allow(self.client_address[0])
        if not allowed:
            self.server.idempotency.discard(idempotency_key, fingerprint)
            self._send_error(
                HTTPStatus.TOO_MANY_REQUESTS,
                "rate_limited",
                "Too many send attempts. Wait before trying again.",
                extra_headers={"Retry-After": str(retry_after)},
            )
            return

        try:
            request = MailRequest.from_payload(payload)
        except ValidationError as error:
            self.server.idempotency.discard(idempotency_key, fingerprint)
            self._send_error(
                HTTPStatus.BAD_REQUEST,
                "validation_error",
                error.message,
                field=error.field_name,
            )
            return
        except Exception:
            self.server.idempotency.discard(idempotency_key, fingerprint)
            LOGGER.exception("Unexpected error while validating a send request")
            self._send_error(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                "validation_failed",
                "The server could not validate this request.",
            )
            return
        finally:
            if isinstance(payload, dict):
                payload["app_password"] = None

        try:
            result = self.server.send_func(request)
        except MailDeliveryError as error:
            status = _delivery_http_status(error.code)
            error_payload: dict[str, object] = {
                "code": error.code,
                "message": error.message,
            }
            if error.refused:
                error_payload["refused"] = list(error.refused)
            response: dict[str, object] = {
                "ok": False,
                "error": error_payload,
            }
            self.server.idempotency.complete(
                idempotency_key, fingerprint, status, response
            )
            self._send_json(status, response)
            return
        except Exception:
            LOGGER.exception("Unexpected error while processing a send request")
            status = HTTPStatus.INTERNAL_SERVER_ERROR
            response = {
                "ok": False,
                "error": {
                    "code": "delivery_unknown",
                    "message": "The server lost the delivery result. Check Sent Mail before trying again.",
                },
            }
            self.server.idempotency.complete(
                idempotency_key, fingerprint, status, response
            )
            self._send_json(status, response)
            return

        status_text = "partial" if result.partial else "accepted"
        message = (
            "The provider accepted the message for some recipients."
            if result.partial
            else "The provider accepted the message for delivery."
        )
        response = {
            "ok": True,
            "status": status_text,
            "message": message,
            "accepted": list(result.accepted),
            "refused": list(result.refused),
        }
        self.server.idempotency.complete(
            idempotency_key, fingerprint, HTTPStatus.OK, response
        )
        self._send_json(HTTPStatus.OK, response)

    def _valid_host(self) -> bool:
        host = self.headers.get("Host", "")
        try:
            parsed_host = urlsplit(f"//{host}").hostname
        except ValueError:
            return False
        if not parsed_host:
            return False
        return parsed_host.casefold().rstrip(".") in {"localhost", "127.0.0.1", "::1"}

    def _valid_origin(self) -> bool:
        origin = self.headers.get("Origin")
        if not origin:
            return True
        try:
            parsed = urlsplit(origin)
        except ValueError:
            return False
        if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
            return False
        request_host = self.headers.get("Host", "")
        return parsed.scheme == "http" and parsed.netloc.casefold() == request_host.casefold()

    def _send_error(
        self,
        status: HTTPStatus,
        code: str,
        message: str,
        *,
        field: str | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        error: dict[str, object] = {"code": code, "message": message}
        if field:
            error["field"] = field
        self._send_json(status, {"ok": False, "error": error}, extra_headers=extra_headers)

    def _send_json(
        self,
        status: HTTPStatus,
        payload: dict[str, object],
        *,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        content = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self._security_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(content)))
        if extra_headers:
            for name, value in extra_headers.items():
                self.send_header(name, value)
        self.end_headers()
        self.wfile.write(content)

    def _security_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
            "connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; "
            "form-action 'self'; manifest-src 'self'",
        )

    def log_message(self, message_format: str, *args: object) -> None:
        LOGGER.info("%s - %s", self.client_address[0], message_format % args)


def _delivery_http_status(code: str) -> HTTPStatus:
    if code in {"auth_failed", "recipients_refused", "sender_refused", "provider_rejected"}:
        return HTTPStatus.UNPROCESSABLE_ENTITY
    if code == "delivery_unknown":
        return HTTPStatus.GATEWAY_TIMEOUT
    if code == "provider_temporary":
        return HTTPStatus.SERVICE_UNAVAILABLE
    if code == "provider_unavailable":
        return HTTPStatus.BAD_REQUEST
    return HTTPStatus.BAD_GATEWAY


def _payload_fingerprint(payload: object) -> str:
    safe_payload = dict(payload) if isinstance(payload, dict) else payload
    if isinstance(safe_payload, dict) and "app_password" in safe_payload:
        safe_payload["app_password"] = "<redacted>"
    canonical = json.dumps(
        safe_payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def create_server(
    host: str = "127.0.0.1",
    port: int = 8765,
    *,
    send_func: Callable[[MailRequest], SendResult] = send_email,
    rate_limit: int = 10,
) -> EmailerHTTPServer:
    return EmailerHTTPServer(
        (host, port),
        send_func=send_func,
        rate_limit=rate_limit,
    )
