import io
import os
import unittest
from unittest.mock import patch

from emailer.__main__ import main
from emailer.mailer import SendResult


class CliTests(unittest.TestCase):
    def test_dry_run_validates_and_previews_without_a_credential(self):
        stdout = io.StringIO()
        stderr = io.StringIO()

        with patch.dict(os.environ, {}, clear=True), patch(
            "emailer.__main__.send_email"
        ) as mocked_send:
            result = main(
                [
                    "send",
                    "--provider",
                    "gmail",
                    "--from",
                    "sender@gmail.com",
                    "--to",
                    "one@example.net,two@example.net",
                    "--subject",
                    "CLI test",
                    "--body",
                    "Hello from the terminal.",
                    "--dry-run",
                ],
                stdin=io.StringIO(),
                stdout=stdout,
                stderr=stderr,
            )

        self.assertEqual(result, 0)
        self.assertIn("Dry run: no network connection was made.", stdout.getvalue())
        self.assertIn("one@example.net, two@example.net", stdout.getvalue())
        self.assertEqual(stderr.getvalue(), "")
        mocked_send.assert_not_called()

    def test_sends_with_environment_credential_without_prompting(self):
        stdout = io.StringIO()
        received = []

        def fake_send(request, *, provider_override):
            received.append((request, provider_override))
            return SendResult(accepted=request.recipients, refused=())

        with patch.dict(os.environ, {"EMAILER_PASSWORD": "provider-secret"}, clear=True), patch(
            "emailer.__main__.getpass.getpass"
        ) as mocked_prompt, patch("emailer.__main__.send_email", side_effect=fake_send):
            result = main(
                [
                    "send",
                    "--provider",
                    "yahoo",
                    "--from",
                    "sender@yahoo.com",
                    "--to",
                    "person@example.net",
                    "--subject",
                    "Hello",
                    "--body-file",
                    "-",
                ],
                stdin=io.StringIO("Message from stdin"),
                stdout=stdout,
                stderr=io.StringIO(),
            )

        self.assertEqual(result, 0)
        self.assertEqual(received[0][0].app_password, "provider-secret")
        self.assertEqual(received[0][0].body, "Message from stdin")
        self.assertEqual(received[0][1].smtp_host, "smtp.mail.yahoo.com")
        self.assertIn("accepted 1 recipient", stdout.getvalue())
        mocked_prompt.assert_not_called()

    def test_custom_smtp_configuration_is_cli_only(self):
        received = []

        def fake_send(request, *, provider_override):
            received.append((request, provider_override))
            return SendResult(accepted=request.recipients, refused=())

        with patch.dict(os.environ, {"SMTP_SECRET": "secret"}, clear=True), patch(
            "emailer.__main__.send_email", side_effect=fake_send
        ):
            result = main(
                [
                    "send",
                    "--provider",
                    "custom",
                    "--smtp-host",
                    "mail.example.com",
                    "--smtp-port",
                    "587",
                    "--smtp-security",
                    "starttls",
                    "--credential-env",
                    "SMTP_SECRET",
                    "--username",
                    "smtp-user",
                    "--from",
                    "sender@example.com",
                    "--to",
                    "person@example.net",
                    "--subject",
                    "Custom SMTP",
                    "--body",
                    "Hello",
                ],
                stdin=io.StringIO(),
                stdout=io.StringIO(),
                stderr=io.StringIO(),
            )

        self.assertEqual(result, 0)
        self.assertEqual(received[0][0].auth_username, "smtp-user")
        self.assertEqual(received[0][1].smtp_host, "mail.example.com")
        self.assertEqual(received[0][1].security, "starttls")

    def test_outlook_explains_oauth_requirement_before_prompting(self):
        stderr = io.StringIO()

        with patch("emailer.__main__.getpass.getpass") as mocked_prompt:
            result = main(
                [
                    "send",
                    "--provider",
                    "outlook",
                    "--from",
                    "sender@outlook.com",
                    "--to",
                    "person@example.net",
                    "--subject",
                    "Hello",
                    "--body",
                    "Message",
                ],
                stdin=io.StringIO(),
                stdout=io.StringIO(),
                stderr=stderr,
            )

        self.assertEqual(result, 2)
        self.assertIn("OAuth2", stderr.getvalue())
        mocked_prompt.assert_not_called()


if __name__ == "__main__":
    unittest.main()
