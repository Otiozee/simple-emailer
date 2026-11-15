import smtplib
import ssl
import unittest

from emailer.mailer import MailDeliveryError, build_message, send_email
from emailer.models import MailRequest

from tests.test_models import valid_payload


class FakeSMTP:
    def __init__(self, refused=None, login_error=None, send_error=None):
        self.refused = refused or {}
        self.login_error = login_error
        self.send_error = send_error
        self.login_args = None
        self.message = None
        self.envelope = None
        self.quit_called = False

    def login(self, username, password):
        self.login_args = (username, password)
        if self.login_error:
            raise self.login_error

    def send_message(self, message, from_addr, to_addrs):
        self.message = message
        self.envelope = (from_addr, tuple(to_addrs))
        if self.send_error:
            raise self.send_error
        return self.refused

    def quit(self):
        self.quit_called = True

    def close(self):
        pass


class MailerTests(unittest.TestCase):
    def test_builds_standard_headers_and_keeps_bcc_out_of_message(self):
        request = MailRequest.from_payload(
            valid_payload(
                sender_name="Sender Name",
                cc=["copy@example.net"],
                bcc=["hidden@example.net"],
                reply_to="reply@example.com",
            )
        )

        message = build_message(request)

        self.assertEqual(message["To"], "person@example.net")
        self.assertEqual(message["Cc"], "copy@example.net")
        self.assertEqual(message["Reply-To"], "reply@example.com")
        self.assertIsNone(message["Bcc"])
        self.assertIsNotNone(message["Date"])
        self.assertTrue(message["Message-ID"].endswith("@example.com>"))
        self.assertEqual(message["Content-Transfer-Encoding"], "quoted-printable")

    def test_structures_sender_display_name(self):
        request = MailRequest.from_payload(valid_payload(sender_name="Sender, CEO"))

        message = build_message(request)

        self.assertEqual(message["From"].addresses[0].display_name, "Sender, CEO")
        self.assertEqual(message["From"].addresses[0].addr_spec, "sender@example.com")

    def test_uses_verified_tls_and_explicit_envelope(self):
        request = MailRequest.from_payload(
            valid_payload(bcc=["hidden@example.net"])
        )
        fake = FakeSMTP()
        connection = {}

        def factory(host, port, **kwargs):
            connection.update(host=host, port=port, kwargs=kwargs)
            return fake

        result = send_email(request, smtp_ssl_factory=factory)

        self.assertEqual(connection["host"], "smtp.gmail.com")
        self.assertEqual(connection["port"], 465)
        self.assertTrue(connection["kwargs"]["context"].check_hostname)
        self.assertEqual(fake.login_args, ("sender@example.com", "secret-app-password"))
        self.assertEqual(
            fake.envelope,
            ("sender@example.com", ("person@example.net", "hidden@example.net")),
        )
        self.assertEqual(result.accepted, request.recipients)
        self.assertTrue(fake.quit_called)

    def test_uses_an_explicit_smtp_username(self):
        request = MailRequest.from_payload(valid_payload(auth_username="smtp-user"))
        fake = FakeSMTP()

        send_email(request, smtp_ssl_factory=lambda *args, **kwargs: fake)

        self.assertEqual(fake.login_args, ("smtp-user", "secret-app-password"))

    def test_reports_partial_recipient_refusal(self):
        request = MailRequest.from_payload(
            valid_payload(cc=["refused@example.net"])
        )
        fake = FakeSMTP(refused={"refused@example.net": (550, b"no")})

        result = send_email(request, smtp_ssl_factory=lambda *args, **kwargs: fake)

        self.assertEqual(result.accepted, ("person@example.net",))
        self.assertEqual(result.refused, ("refused@example.net",))
        self.assertTrue(result.partial)

    def test_translates_authentication_failure(self):
        request = MailRequest.from_payload(valid_payload())
        fake = FakeSMTP(login_error=smtplib.SMTPAuthenticationError(535, b"bad login"))

        with self.assertRaises(MailDeliveryError) as caught:
            send_email(request, smtp_ssl_factory=lambda *args, **kwargs: fake)

        self.assertEqual(caught.exception.code, "auth_failed")
        self.assertNotIn("bad login", caught.exception.message)

    def test_marks_disconnect_during_send_as_unknown(self):
        request = MailRequest.from_payload(valid_payload())
        fake = FakeSMTP(send_error=smtplib.SMTPServerDisconnected("lost"))

        with self.assertRaises(MailDeliveryError) as caught:
            send_email(request, smtp_ssl_factory=lambda *args, **kwargs: fake)

        self.assertEqual(caught.exception.code, "delivery_unknown")

    def test_marks_tls_failure_during_send_as_unknown(self):
        request = MailRequest.from_payload(valid_payload())
        fake = FakeSMTP(send_error=ssl.SSLError("lost"))

        with self.assertRaises(MailDeliveryError) as caught:
            send_email(request, smtp_ssl_factory=lambda *args, **kwargs: fake)

        self.assertEqual(caught.exception.code, "delivery_unknown")

    def test_classifies_temporary_provider_response(self):
        request = MailRequest.from_payload(valid_payload())
        fake = FakeSMTP(login_error=smtplib.SMTPAuthenticationError(454, b"later"))

        with self.assertRaises(MailDeliveryError) as caught:
            send_email(request, smtp_ssl_factory=lambda *args, **kwargs: fake)

        self.assertEqual(caught.exception.code, "provider_temporary")


if __name__ == "__main__":
    unittest.main()
