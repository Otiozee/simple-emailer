import json
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from emailer.mailer import SendResult
from emailer.server import create_server

from tests.test_models import valid_payload


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.received = []

        def fake_send(request):
            self.received.append(request)
            return SendResult(accepted=request.recipients, refused=())

        self.server = create_server(port=0, send_func=fake_send, rate_limit=100)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.origin = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def request(self, path, *, method="GET", payload=None, headers=None):
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request_headers = headers or {}
        if payload is not None:
            request_headers.setdefault("Content-Type", "application/json")
        request = Request(
            f"{self.origin}{path}",
            data=data,
            headers=request_headers,
            method=method,
        )
        with urlopen(request, timeout=2) as response:
            return response.status, dict(response.headers), response.read()

    def test_serves_frontend_with_security_headers(self):
        status, headers, body = self.request("/")

        self.assertEqual(status, 200)
        self.assertIn(b"Simple Emailer", body)
        self.assertIn("default-src 'self'", headers["Content-Security-Policy"])
        self.assertEqual(headers["X-Frame-Options"], "DENY")
        self.assertNotIn(b'name="app_password"', body)
        self.assertIn(b'id="review-button"', body)

    def test_provider_api_marks_outlook_unavailable(self):
        status, _, body = self.request("/api/providers")
        providers = json.loads(body)["providers"]
        outlook = next(provider for provider in providers if provider["id"] == "outlook")

        self.assertEqual(status, 200)
        self.assertFalse(outlook["enabled"])
        self.assertEqual(outlook["auth_method"], "oauth2")
        self.assertNotIn("smtp_host", outlook)

    def test_send_endpoint_validates_and_dispatches(self):
        status, headers, body = self.request(
            "/api/send",
            method="POST",
            payload=valid_payload(),
            headers={
                "Origin": self.origin,
                "X-Emailer-Request": "send-message",
                "Idempotency-Key": "test-send-request-0001",
            },
        )
        response = json.loads(body)

        self.assertEqual(status, 200)
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertTrue(response["ok"])
        self.assertEqual(response["status"], "accepted")
        self.assertEqual(len(self.received), 1)

    def test_replays_idempotent_result_without_sending_twice(self):
        headers = {
            "Origin": self.origin,
            "X-Emailer-Request": "send-message",
            "Idempotency-Key": "test-replay-request-0001",
        }

        first = self.request("/api/send", method="POST", payload=valid_payload(), headers=headers)
        second = self.request("/api/send", method="POST", payload=valid_payload(), headers=headers)

        self.assertEqual(first[0], 200)
        self.assertEqual(second[0], 200)
        self.assertEqual(json.loads(first[2]), json.loads(second[2]))
        self.assertEqual(len(self.received), 1)

    def test_rejects_malformed_address_as_validation_error(self):
        with self.assertRaises(HTTPError) as caught:
            self.request(
                "/api/send",
                method="POST",
                payload=valid_payload(to=["person@example..net"]),
                headers={
                    "Origin": self.origin,
                    "X-Emailer-Request": "send-message",
                    "Idempotency-Key": "test-invalid-address-001",
                },
            )

        self.assertEqual(caught.exception.code, 400)
        response = json.loads(caught.exception.read())
        self.assertEqual(response["error"]["code"], "validation_error")

    def test_rejects_cross_origin_send(self):
        with self.assertRaises(HTTPError) as caught:
            self.request(
                "/api/send",
                method="POST",
                payload=valid_payload(),
                headers={
                    "Origin": "https://evil.example",
                    "X-Emailer-Request": "send-message",
                },
            )

        self.assertEqual(caught.exception.code, 403)
        self.assertEqual(self.received, [])

    def test_rejects_other_loopback_origin_port(self):
        with self.assertRaises(HTTPError) as caught:
            self.request(
                "/api/send",
                method="POST",
                payload=valid_payload(),
                headers={
                    "Origin": "http://127.0.0.1:1",
                    "X-Emailer-Request": "send-message",
                    "Idempotency-Key": "test-wrong-origin-0001",
                },
            )

        self.assertEqual(caught.exception.code, 403)

    def test_rejects_missing_custom_header(self):
        with self.assertRaises(HTTPError) as caught:
            self.request(
                "/api/send",
                method="POST",
                payload=valid_payload(),
                headers={"Origin": self.origin},
            )

        self.assertEqual(caught.exception.code, 403)

    def test_rejects_non_loopback_server_binding(self):
        with self.assertRaisesRegex(ValueError, "loopback"):
            create_server(host="0.0.0.0", port=0)


if __name__ == "__main__":
    unittest.main()
