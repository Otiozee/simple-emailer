# Simple Emailer

Simple Emailer is a local CLI and optional web interface for sending plain-text email through an existing SMTP account. It runs on Python 3.11+, stores no credentials, and has no runtime dependencies.

Email cannot be delivered through Gmail, Yahoo, Outlook, or another reputable provider without that provider authenticating the sender. Simple Emailer has no separate application login, but the SMTP provider still requires an app password or OAuth. The CLI securely prompts for an app password, or reads it from an environment variable so automated commands need no interactive login.

- [PyPI package](https://pypi.org/project/simple-emailer/)
- [GitHub repository](https://github.com/otiozee/simple-emailer)

## Install

[`pipx`](https://pipx.pypa.io/) installs the application in an isolated environment and makes `simple-emailer` available from any directory for the current user.

On Debian, Ubuntu, or WSL, install `pipx` first:

```bash
sudo apt update
sudo apt install pipx
pipx ensurepath
```

Restart the terminal, then install Simple Emailer from PyPI:

```bash
pipx install simple-emailer
simple-emailer --version
```

Expected version output:

```text
simple-emailer 0.2.1
```

On macOS with Homebrew:

```bash
brew install pipx
pipx ensurepath
pipx install simple-emailer
```

On Windows PowerShell:

```powershell
py -m pip install --user pipx
py -m pipx ensurepath
```

Restart PowerShell, then run:

```powershell
pipx install simple-emailer
simple-emailer --version
```

The latest GitHub source can be installed instead of the PyPI release:

```bash
pipx install "git+https://github.com/otiozee/simple-emailer.git"
```

Do not use `sudo pip`, `pip --break-system-packages`, or modify the operating system's Python installation.

Upgrade or remove the application with:

```bash
pipx upgrade simple-emailer
pipx uninstall simple-emailer
```

## Quick Start

List available providers:

```bash
simple-emailer providers
```

Send through Gmail:

```bash
simple-emailer send \
  --provider gmail \
  --from you@gmail.com \
  --to recipient@example.com \
  --subject "Hello" \
  --body "Sent from my terminal"
```

The command securely prompts for the provider-generated app password. Typed password characters are intentionally not displayed. Replace the example addresses with real addresses.

Gmail requires 2-Step Verification and a [Google app password](https://support.google.com/accounts/answer/185833). Yahoo requires a [third-party app password](https://help.yahoo.com/kb/generate-manage-third-party-passwords-sln15241.html). Normal account passwords usually will not work.

Run a validation and preview without a credential, SMTP connection, or delivery:

```bash
simple-emailer send \
  --provider gmail \
  --from you@gmail.com \
  --to recipient@example.com \
  --subject "Preview" \
  --body "Nothing will be sent" \
  --dry-run
```

## Write Messages

Use Bash's `$'...'` quoting for multiple lines. `\n` adds one newline and `\n\n` adds a blank line:

```bash
simple-emailer send \
  --provider gmail \
  --from you@gmail.com \
  --to recipient@example.com \
  --subject "Hello" \
  --body $'Hello,\n\nThis is the first paragraph.\nThis is another line.\n\nRegards,\nYour Name'
```

In Windows PowerShell, put a multiline message in a variable:

```powershell
$body = @"
Hello,

This is the first paragraph.

Regards,
Your Name
"@

simple-emailer send `
  --provider gmail `
  --from you@gmail.com `
  --to recipient@example.com `
  --subject "Hello" `
  --body $body
```

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

Available message options include:

- `--to`, `--cc`, `--bcc`: repeat these options for multiple recipients.
- `--reply-to`: set a different reply address.
- `--body`, `--body-file`: provide plain-text content directly, from a file, or from standard input.
- `--attach`: repeat this option to attach up to 5 files and 12 MB total.
- `--name`: set the sender's display name.
- `--dry-run`: validate and preview without sending.

Run `simple-emailer send --help` for every option.

## Credentials

For interactive use, leave `EMAILER_PASSWORD` unset. The CLI will ask for the app password and hold it only for the current send operation.

For automation, read the app password into the environment without adding it to shell history:

```bash
read -rsp "App password: " EMAILER_PASSWORD
export EMAILER_PASSWORD
printf '\n'
```

Send the message, then remove the variable:

```bash
simple-emailer send \
  --provider gmail \
  --from you@gmail.com \
  --to recipient@example.com \
  --subject "Automated message" \
  --body "Hello"

unset EMAILER_PASSWORD
```

The credential is deliberately not accepted as a command-line argument because arguments can leak through shell history and process listings.

## Delivery Result

A successful SMTP submission prints:

```text
Provider accepted 1 recipient(s).
```

This means the provider accepted the message for delivery. It does not guarantee that the destination server will place it in the recipient's inbox.

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

Use `--smtp-security tls` with the provider's implicit TLS port, commonly `465`. Use `--smtp-security starttls` with its STARTTLS port, commonly `587`. Omit `--username` when the SMTP username is the same as the `--from` address.

Custom SMTP supports password or app-password authentication. It does not add OAuth support and therefore cannot bypass Outlook's OAuth requirement.

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

For development from a source checkout, install an editable copy into pipx:

```bash
pipx install --editable .
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
