import base64
import unittest

from emailer.models import MailRequest, ValidationError


def valid_payload(**overrides):
    payload = {
        "provider": "gmail",
        "sender_email": "sender@example.com",
        "app_password": "secret-app-password",
        "to": ["person@example.net"],
        "cc": [],
        "bcc": [],
        "subject": "Hello",
        "body": "Test message",
        "attachments": [],
    }
    payload.update(overrides)
    return payload


class MailRequestTests(unittest.TestCase):
    def test_parses_valid_payload_without_exposing_secret_in_repr(self):
        request = MailRequest.from_payload(valid_payload())

        self.assertEqual(request.provider_id, "gmail")
        self.assertEqual(request.recipients, ("person@example.net",))
        self.assertNotIn("secret-app-password", repr(request))

    def test_deduplicates_domains_case_insensitively_but_preserves_local_case(self):
        request = MailRequest.from_payload(
            valid_payload(
                to=["person@example.net"],
                cc=["copy@example.net"],
                bcc=["PERSON@example.net", "hidden@example.net"],
            )
        )

        self.assertEqual(
            request.recipients,
            (
                "person@example.net",
                "copy@example.net",
                "PERSON@example.net",
                "hidden@example.net",
            ),
        )

    def test_deduplicates_domain_case_variants(self):
        request = MailRequest.from_payload(
            valid_payload(bcc=["person@EXAMPLE.NET", "hidden@example.net"])
        )

        self.assertEqual(request.recipients, ("person@example.net", "hidden@example.net"))

    def test_rejects_disabled_outlook_password_flow(self):
        with self.assertRaises(ValidationError) as caught:
            MailRequest.from_payload(valid_payload(provider="outlook"))

        self.assertEqual(caught.exception.field_name, "provider")
        self.assertIn("OAuth2", caught.exception.message)

    def test_rejects_header_injection(self):
        with self.assertRaises(ValidationError):
            MailRequest.from_payload(valid_payload(subject="Hello\nBcc: victim@example.net"))

    def test_rejects_non_ascii_provider_credentials(self):
        with self.assertRaises(ValidationError) as caught:
            MailRequest.from_payload(valid_payload(app_password="secret-password-\u00e9"))

        self.assertEqual(caught.exception.field_name, "app_password")

    def test_rejects_body_control_characters(self):
        with self.assertRaises(ValidationError) as caught:
            MailRequest.from_payload(valid_payload(body="Hello\x00world"))

        self.assertEqual(caught.exception.field_name, "body")

    def test_rejects_malformed_email(self):
        with self.assertRaises(ValidationError) as caught:
            MailRequest.from_payload(valid_payload(to=["not-an-address"]))

        self.assertEqual(caught.exception.field_name, "to")

    def test_sanitizes_attachment_name_and_decodes_content(self):
        request = MailRequest.from_payload(
            valid_payload(
                attachments=[
                    {
                        "filename": "../../notes.txt",
                        "content_type": "text/plain",
                        "content": base64.b64encode(b"notes").decode("ascii"),
                    }
                ]
            )
        )

        self.assertEqual(request.attachments[0].filename, "notes.txt")
        self.assertEqual(request.attachments[0].content, b"notes")

    def test_rejects_invalid_attachment_encoding(self):
        with self.assertRaises(ValidationError) as caught:
            MailRequest.from_payload(
                valid_payload(
                    attachments=[
                        {
                            "filename": "notes.txt",
                            "content_type": "text/plain",
                            "content": "not base64!",
                        }
                    ]
                )
            )

        self.assertEqual(caught.exception.field_name, "attachments")

    def test_replaces_multipart_attachment_content_type(self):
        request = MailRequest.from_payload(
            valid_payload(
                attachments=[
                    {
                        "filename": "data.bin",
                        "content_type": "multipart/mixed",
                        "content": base64.b64encode(b"data").decode("ascii"),
                    }
                ]
            )
        )

        self.assertEqual(request.attachments[0].content_type, "application/octet-stream")


if __name__ == "__main__":
    unittest.main()
