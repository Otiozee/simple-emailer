"""Command-line interface for Simple Emailer."""

import argparse
import base64
import getpass
import logging
import os
import sys
import threading
import webbrowser
from pathlib import Path
from typing import Sequence, TextIO

from . import __version__
from .mailer import MailDeliveryError, build_message, send_email
from .models import MailRequest, ValidationError
from .providers import PROVIDERS, Provider, get_provider
from .server import create_server


def _add_web_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--host",
        choices=("127.0.0.1", "localhost"),
        default="127.0.0.1",
        help="loopback address to bind (default: 127.0.0.1)",
    )
    parser.add_argument("--port", type=int, default=8765, help="port to bind (default: 8765)")
    parser.add_argument("--no-browser", action="store_true", help="do not open a browser")
    parser.add_argument("--verbose", action="store_true", help="enable request logging")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="simple-emailer",
        description="Send email securely from a terminal or run the local web interface.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    _add_web_options(parser)
    commands = parser.add_subparsers(dest="command")

    send_parser = commands.add_parser("send", help="send an email from the terminal")
    send_parser.add_argument(
        "--provider",
        required=True,
        choices=(*PROVIDERS.keys(), "custom"),
        help="sender's email provider",
    )
    send_parser.add_argument("--from", dest="sender_email", required=True, help="sender address")
    send_parser.add_argument("--name", default="", help="sender display name")
    send_parser.add_argument(
        "--username", help="SMTP login name when it differs from the sender address"
    )
    send_parser.add_argument(
        "--to", action="append", required=True, metavar="ADDRESS", help="recipient; repeat as needed"
    )
    send_parser.add_argument(
        "--cc", action="append", default=[], metavar="ADDRESS", help="Cc recipient; repeat as needed"
    )
    send_parser.add_argument(
        "--bcc", action="append", default=[], metavar="ADDRESS", help="Bcc recipient; repeat as needed"
    )
    send_parser.add_argument("--reply-to", help="reply-to address")
    send_parser.add_argument("--subject", required=True, help="message subject")
    body_group = send_parser.add_mutually_exclusive_group()
    body_group.add_argument("--body", help="plain-text message body")
    body_group.add_argument(
        "--body-file", metavar="PATH", help="read the body from PATH, or - for standard input"
    )
    send_parser.add_argument(
        "--attach", action="append", default=[], metavar="PATH", help="attachment; repeat as needed"
    )
    send_parser.add_argument(
        "--credential-env",
        default="EMAILER_PASSWORD",
        metavar="NAME",
        help="environment variable containing the SMTP/app password (default: EMAILER_PASSWORD)",
    )
    send_parser.add_argument("--smtp-host", help="custom provider SMTP hostname")
    send_parser.add_argument("--smtp-port", type=int, help="custom provider SMTP port")
    send_parser.add_argument(
        "--smtp-security", choices=("tls", "starttls"), help="custom provider TLS mode"
    )
    send_parser.add_argument(
        "--dry-run", action="store_true", help="validate and preview without connecting to SMTP"
    )

    commands.add_parser("providers", help="list provider support and SMTP requirements")
    web_parser = commands.add_parser("web", help="run the local web interface")
    _add_web_options(web_parser)
    return parser


def _split_addresses(values: Sequence[str]) -> list[str]:
    return [address.strip() for value in values for address in value.split(",") if address.strip()]


def _custom_provider(args: argparse.Namespace, parser: argparse.ArgumentParser) -> Provider:
    missing = [
        option
        for option, value in (
            ("--smtp-host", args.smtp_host),
            ("--smtp-port", args.smtp_port),
            ("--smtp-security", args.smtp_security),
        )
        if value is None
    ]
    if missing:
        parser.error(f"custom provider requires {', '.join(missing)}")
    if not 1 <= args.smtp_port <= 65535:
        parser.error("--smtp-port must be between 1 and 65535")
    host = args.smtp_host.strip()
    if not host or any(character.isspace() for character in host):
        parser.error("--smtp-host must be a valid hostname")
    return Provider(
        id="custom",
        name="Custom SMTP",
        smtp_host=host,
        smtp_port=args.smtp_port,
        security=args.smtp_security,
        auth_method="password",
        enabled=True,
        help_url="",
        guidance="User-supplied SMTP configuration.",
    )


def _read_body(args: argparse.Namespace, parser: argparse.ArgumentParser, stdin: TextIO) -> str:
    if args.body is not None:
        return args.body
    if args.body_file is not None:
        if args.body_file == "-":
            return stdin.read()
        try:
            return Path(args.body_file).read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            parser.error(f"cannot read body file {args.body_file!r}: {error}")
    if not stdin.isatty():
        return stdin.read()
    parser.error("provide --body, --body-file, or pipe the message body on standard input")


def _read_attachments(paths: Sequence[str], parser: argparse.ArgumentParser) -> list[dict[str, str]]:
    attachments = []
    for raw_path in paths:
        path = Path(raw_path)
        try:
            content = path.read_bytes()
        except OSError as error:
            parser.error(f"cannot read attachment {raw_path!r}: {error}")
        attachments.append(
            {
                "filename": path.name,
                "content": base64.b64encode(content).decode("ascii"),
            }
        )
    return attachments


def _print_preview(request: MailRequest, provider: Provider, stdout: TextIO) -> None:
    message = build_message(request)
    print("Dry run: no network connection was made.", file=stdout)
    print(f"Provider: {provider.name} ({provider.smtp_host}:{provider.smtp_port}, {provider.security})", file=stdout)
    print(f"Envelope from: {request.sender_email}", file=stdout)
    print(f"Envelope recipients: {', '.join(request.recipients)}", file=stdout)
    for name in ("From", "To", "Cc", "Reply-To", "Subject"):
        if message[name]:
            print(f"{name}: {message[name]}", file=stdout)
    print(f"Body: {len(request.body)} characters", file=stdout)
    if request.attachments:
        summary = ", ".join(
            f"{attachment.filename} ({len(attachment.content)} bytes)"
            for attachment in request.attachments
        )
        print(f"Attachments: {summary}", file=stdout)


def _run_send(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    *,
    stdin: TextIO,
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    provider = _custom_provider(args, parser) if args.provider == "custom" else get_provider(args.provider)
    if provider is None:
        parser.error("unknown provider")
    if not provider.enabled:
        print(provider.unavailable_reason or "This provider is not available.", file=stderr)
        return 2

    credential = "dry-run-placeholder" if args.dry_run else os.environ.get(args.credential_env)
    if not credential:
        credential = getpass.getpass(f"{provider.name} SMTP/app password: ")

    payload = {
        "provider": provider.id,
        "sender_email": args.sender_email,
        "sender_name": args.name,
        "auth_username": args.username,
        "app_password": credential,
        "to": _split_addresses(args.to),
        "cc": _split_addresses(args.cc),
        "bcc": _split_addresses(args.bcc),
        "reply_to": args.reply_to,
        "subject": args.subject,
        "body": _read_body(args, parser, stdin),
        "attachments": _read_attachments(args.attach, parser),
    }
    try:
        request = MailRequest.from_payload(payload, provider_override=provider)
    except ValidationError as error:
        location = f" ({error.field_name})" if error.field_name else ""
        print(f"Invalid message{location}: {error.message}", file=stderr)
        return 2
    finally:
        payload["app_password"] = None

    if args.dry_run:
        _print_preview(request, provider, stdout)
        return 0
    try:
        result = send_email(request, provider_override=provider)
    except MailDeliveryError as error:
        print(f"Send failed [{error.code}]: {error.message}", file=stderr)
        return 1

    print(f"Provider accepted {len(result.accepted)} recipient(s).", file=stdout)
    if result.refused:
        print(f"Refused: {', '.join(result.refused)}", file=stderr)
        return 1
    return 0


def _run_providers(stdout: TextIO) -> int:
    for provider in PROVIDERS.values():
        status = "available" if provider.enabled else "unavailable"
        print(f"{provider.id:8} {status:11} {provider.name}: {provider.guidance}", file=stdout)
    print("custom   available   Any SMTP service with password authentication and TLS.", file=stdout)
    return 0


def _run_web(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    if not 0 <= args.port <= 65535:
        parser.error("port must be between 0 and 65535")
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    server = create_server(host=args.host, port=args.port)
    actual_port = server.server_address[1]
    display_url = f"http://{args.host}:{actual_port}"
    print(f"Simple Emailer is running at {display_url}")
    print("Press Ctrl+C to stop. App passwords are held only for the current send request.")
    if not args.no_browser:
        threading.Timer(0.25, webbrowser.open, args=(display_url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Simple Emailer.")
    finally:
        server.server_close()
    return 0


def main(
    argv: list[str] | None = None,
    *,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr
    if args.command == "send":
        return _run_send(args, parser, stdin=stdin, stdout=stdout, stderr=stderr)
    if args.command == "providers":
        return _run_providers(stdout)
    return _run_web(args, parser)


if __name__ == "__main__":
    raise SystemExit(main())
