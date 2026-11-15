"""Input validation and immutable mail request models."""

import base64
import binascii
import mimetypes
import re
import unicodedata
from dataclasses import dataclass, field
from email.errors import HeaderParseError
from email.headerregistry import Address
from pathlib import PurePosixPath
from typing import Any, Mapping

from .providers import Provider, get_provider


MAX_RECIPIENTS = 50
MAX_SUBJECT_LENGTH = 200
MAX_BODY_LENGTH = 100_000
MAX_ATTACHMENTS = 5
MAX_ATTACHMENT_BYTES = 8 * 1024 * 1024
MAX_TOTAL_ATTACHMENT_BYTES = 12 * 1024 * 1024
MAX_PASSWORD_LENGTH = 1_024

_CONTENT_TYPE = re.compile(r"^[a-z0-9][a-z0-9!#$&^_.+-]*/[a-z0-9][a-z0-9!#$&^_.+-]*$", re.I)


class ValidationError(ValueError):
    def __init__(self, message: str, field_name: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.field_name = field_name


@dataclass(frozen=True, slots=True)
class Attachment:
    filename: str
    content_type: str
    content: bytes = field(repr=False)


@dataclass(frozen=True, slots=True)
class MailRequest:
    provider_id: str
    sender_email: str
    app_password: str = field(repr=False)
    to: tuple[str, ...]
    subject: str
    body: str
    auth_username: str | None = None
    sender_name: str = ""
    cc: tuple[str, ...] = ()
    bcc: tuple[str, ...] = ()
    reply_to: str | None = None
    attachments: tuple[Attachment, ...] = ()

    @property
    def recipients(self) -> tuple[str, ...]:
        unique: list[str] = []
        seen: set[str] = set()
        for address in (*self.to, *self.cc, *self.bcc):
            key = normalized_address_key(address)
            if key not in seen:
                unique.append(address)
                seen.add(key)
        return tuple(unique)

    @classmethod
    def from_payload(
        cls,
        payload: Mapping[str, Any],
        *,
        provider_override: Provider | None = None,
    ) -> "MailRequest":
        if not isinstance(payload, Mapping):
            raise ValidationError("The request body must be a JSON object.")

        provider_id = _required_string(payload, "provider", 30).lower()
        provider = provider_override or get_provider(provider_id)
        if provider_override is not None and provider_override.id != provider_id:
            raise ValidationError("The SMTP provider configuration does not match.", "provider")
        if provider is None:
            raise ValidationError("Select a supported email provider.", "provider")
        if not provider.enabled:
            raise ValidationError(
                provider.unavailable_reason or "This provider is not available.",
                "provider",
            )

        sender_email = _email(
            _required_string(payload, "sender_email", 254),
            "sender_email",
            ascii_only=True,
        )
        app_password = _required_secret(payload, "app_password")
        auth_username_value = _optional_string(payload, "auth_username", 254)
        auth_username = auth_username_value or None
        if auth_username is not None:
            _reject_header_controls(auth_username, "auth_username")
            if not auth_username.isascii():
                raise ValidationError("Use an ASCII SMTP username.", "auth_username")
        sender_name = _optional_string(payload, "sender_name", 100)
        _reject_header_controls(sender_name, "sender_name")

        to = _address_list(payload, "to", required=True)
        cc = _address_list(payload, "cc")
        bcc = _address_list(payload, "bcc")
        if len((*to, *cc, *bcc)) > MAX_RECIPIENTS:
            raise ValidationError(
                f"Use no more than {MAX_RECIPIENTS} recipients per message.",
                "to",
            )

        reply_value = _optional_string(payload, "reply_to", 254)
        reply_to = _email(reply_value, "reply_to") if reply_value else None

        subject = _required_string(payload, "subject", MAX_SUBJECT_LENGTH)
        _reject_header_controls(subject, "subject")
        body = _required_string(payload, "body", MAX_BODY_LENGTH, strip=False)
        _reject_body_controls(body)

        attachments = _attachments(payload.get("attachments", []))
        return cls(
            provider_id=provider_id,
            sender_email=sender_email,
            app_password=app_password,
            auth_username=auth_username,
            sender_name=sender_name,
            to=to,
            cc=cc,
            bcc=bcc,
            reply_to=reply_to,
            subject=subject,
            body=body,
            attachments=attachments,
        )


def _required_string(
    payload: Mapping[str, Any],
    key: str,
    max_length: int,
    *,
    strip: bool = True,
) -> str:
    value = payload.get(key)
    if not isinstance(value, str):
        raise ValidationError("This field is required.", key)
    result = value.strip() if strip else value
    if not result.strip():
        raise ValidationError("This field is required.", key)
    if len(result) > max_length:
        raise ValidationError(f"Use no more than {max_length:,} characters.", key)
    return result


def _optional_string(payload: Mapping[str, Any], key: str, max_length: int) -> str:
    value = payload.get(key, "")
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValidationError("This field must be text.", key)
    result = value.strip()
    if len(result) > max_length:
        raise ValidationError(f"Use no more than {max_length:,} characters.", key)
    return result


def _required_secret(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValidationError("Enter the app password generated by your provider.", key)
    if len(value) > MAX_PASSWORD_LENGTH:
        raise ValidationError("The app password is too long.", key)
    if not value.isascii() or any(not character.isprintable() for character in value):
        raise ValidationError("The app password contains unsupported characters.", key)
    return value


def _reject_header_controls(value: str, field_name: str) -> None:
    if any(unicodedata.category(character) == "Cc" for character in value):
        raise ValidationError("Control characters are not allowed in this field.", field_name)


def _reject_body_controls(value: str) -> None:
    if any(
        unicodedata.category(character) == "Cc" and character not in {"\t", "\r", "\n"}
        for character in value
    ):
        raise ValidationError("The message contains unsupported control characters.", "body")


def _email(value: str, field_name: str, *, ascii_only: bool = False) -> str:
    _reject_header_controls(value, field_name)
    if len(value) > 254 or value != value.strip():
        raise ValidationError("Enter a valid email address.", field_name)
    if ascii_only and not value.isascii():
        raise ValidationError("Use an ASCII email address for provider sign-in.", field_name)
    try:
        parsed = Address(addr_spec=value)
    except (HeaderParseError, IndexError, TypeError, ValueError):
        raise ValidationError("Enter a valid email address.", field_name) from None
    if not parsed.username or not parsed.domain or parsed.addr_spec != value:
        raise ValidationError("Enter a valid email address.", field_name)
    return value


def normalized_address_key(value: str) -> str:
    local_part, domain = value.rsplit("@", 1)
    return f"{local_part}@{domain.casefold()}"


def _address_list(
    payload: Mapping[str, Any], key: str, *, required: bool = False
) -> tuple[str, ...]:
    value = payload.get(key, [])
    if not isinstance(value, list):
        raise ValidationError("Provide addresses as a list.", key)
    if required and not value:
        raise ValidationError("Add at least one recipient.", key)
    addresses: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ValidationError("Each recipient must be an email address.", key)
        addresses.append(_email(item.strip(), key))
    return tuple(addresses)


def _attachments(value: Any) -> tuple[Attachment, ...]:
    if not isinstance(value, list):
        raise ValidationError("Attachments must be a list.", "attachments")
    if len(value) > MAX_ATTACHMENTS:
        raise ValidationError(
            f"Attach no more than {MAX_ATTACHMENTS} files.", "attachments"
        )

    attachments: list[Attachment] = []
    total_size = 0
    max_encoded_length = ((MAX_ATTACHMENT_BYTES + 2) // 3) * 4 + 4
    for raw_attachment in value:
        if not isinstance(raw_attachment, Mapping):
            raise ValidationError("An attachment is malformed.", "attachments")

        raw_name = raw_attachment.get("filename")
        if not isinstance(raw_name, str) or not raw_name.strip():
            raise ValidationError("Every attachment needs a filename.", "attachments")
        filename = PurePosixPath(raw_name.replace("\\", "/")).name.strip()
        _reject_header_controls(filename, "attachments")
        if filename in {"", ".", ".."} or len(filename) > 255:
            raise ValidationError("An attachment filename is invalid.", "attachments")

        encoded = raw_attachment.get("content")
        if not isinstance(encoded, str) or len(encoded) > max_encoded_length:
            raise ValidationError(
                f"Each attachment must be {MAX_ATTACHMENT_BYTES // (1024 * 1024)} MB or smaller.",
                "attachments",
            )
        try:
            content = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError):
            raise ValidationError("An attachment is not valid base64 data.", "attachments") from None
        if len(content) > MAX_ATTACHMENT_BYTES:
            raise ValidationError(
                f"Each attachment must be {MAX_ATTACHMENT_BYTES // (1024 * 1024)} MB or smaller.",
                "attachments",
            )

        total_size += len(content)
        if total_size > MAX_TOTAL_ATTACHMENT_BYTES:
            raise ValidationError(
                f"Attachments must total {MAX_TOTAL_ATTACHMENT_BYTES // (1024 * 1024)} MB or less.",
                "attachments",
            )

        content_type = raw_attachment.get("content_type")
        if not isinstance(content_type, str) or not _CONTENT_TYPE.fullmatch(content_type):
            content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        if content_type.casefold().startswith("multipart/"):
            content_type = "application/octet-stream"
        attachments.append(
            Attachment(filename=filename, content_type=content_type.lower(), content=content)
        )
    return tuple(attachments)
