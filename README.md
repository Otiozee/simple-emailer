# Simple Emailer

Simple Emailer is a local CLI and optional web interface for sending plain-text email through an existing SMTP account. It runs on Python 3.11+, stores no credentials, and has no runtime dependencies.

Email cannot be delivered through Gmail, Yahoo, Outlook, or another reputable provider without that provider authenticating the sender. Simple Emailer has no separate application login, but the SMTP provider still requires an app password or OAuth. The CLI securely prompts for an app password, or reads it from an environment variable so automated commands need no interactive login.

## Install Globally

[`pipx`](https://pipx.pypa.io/) is recommended because it installs an isolated application and exposes `simple-emailer` globally:

```bash
pipx install .
simple-emailer --version
```

For development from this checkout:

```bash
python3 -m pip install -e .
```

## Send From The CLI

Set the provider-generated app password without placing it in shell history:

```bash
read -rsp "App password: " EMAILER_PASSWORD && export EMAILER_PASSWORD
printf '\n'
```

Send a message:

```bash
simple-emailer send \
  --provider gmail \
  --from you@gmail.com \
  --to recipient@example.com \
  --subject "Hello" \
  --body "Sent from my terminal"
```

If `EMAILER_PASSWORD` is not set, the command prompts without displaying the password. The credential is never accepted as a command-line argument, where it could leak through shell history or the process list.

Use a file or standard input for longer messages, and repeat recipient or attachment options:

```bash
simple-emailer send \
  --provider yahoo \
  --from you@yahoo.com \
  --to first@example.com \
  --to second@example.com \
  --cc copy@example.com \
  --subject "Report" \
  --body-file message.txt \
  --attach report.pdf

printf 'Message from a pipeline\n' | simple-emailer send \
  --provider gmail \
  --from you@gmail.com \
  --to recipient@example.com \
  --subject "Piped message"
```

Run a complete validation and preview without a credential or network connection:

```bash
simple-emailer send \
  --provider gmail \
  --from you@gmail.com \
  --to recipient@example.com \
  --subject "Preview" \
  --body "Nothing will be sent" \
  --dry-run
```

Example output:

```text
Dry run: no network connection was made.
Provider: Gmail (smtp.gmail.com:465, tls)
Envelope from: you@gmail.com
Envelope recipients: recipient@example.com
From: you@gmail.com
To: recipient@example.com
Subject: Preview
Body: 20 characters
```

## Provider Support

Run `simple-emailer providers` to see the built-in status.

| Provider | Authentication | Status |
| --- | --- | --- |
| Gmail | App password with 2-Step Verification | Supported |
| Yahoo Mail | Third-party app password | Supported |
| Outlook.com | OAuth2 / Modern Auth | Not yet supported |
| Other SMTP services | Password/app password over TLS | Supported with `custom` |

Microsoft requires OAuth2 for Outlook.com SMTP. A distributable OAuth client requires an application registration, redirect URI, consent configuration, and secure token storage. Until those product credentials exist, Simple Emailer reports Outlook as unavailable rather than attempting obsolete Basic Authentication.

For another SMTP provider, use its documented host, port, TLS mode, and password. This is intentionally available only in the local CLI; the web API retains a fixed provider allowlist.

```bash
simple-emailer send \
  --provider custom \
  --smtp-host smtp.example.com \
  --smtp-port 587 \
  --smtp-security starttls \
  --username account-name \
  --from sender@example.com \
  --to recipient@example.net \
  --subject "Custom SMTP" \
  --body "Hello"
```

## Local Web Interface

The original local-first PWA remains available:

```bash
simple-emailer web
```

It opens at `http://127.0.0.1:8765`. `simple-emailer` with no subcommand and `python3 msg.py` remain compatible aliases. Use `--no-browser` to prevent automatic browser launch.

## Test

Tests never contact a real SMTP server:

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q emailer tests msg.py
```

## Security Model

- SMTP certificates and hostnames are verified with the operating system trust store.
- TLS 1.2 or newer is required.
- Credentials are held only for the current process and are not logged or written by the application.
- Bcc addresses are used only in the SMTP envelope and omitted from message headers.
- Attachments are capped at 5 files, 8 MB each, and 12 MB total.
- The web server accepts only loopback bindings and same-origin API requests.
- The browser API cannot select arbitrary SMTP hosts.

Environment variables can be inspected by sufficiently privileged local processes. For interactive use, leave `EMAILER_PASSWORD` unset and use the hidden prompt. Revoke an app password if a device or credential is compromised. See [SECURITY.md](SECURITY.md) and [docs/ROADMAP.md](docs/ROADMAP.md).
