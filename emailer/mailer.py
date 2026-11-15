"""Secure MIME construction and SMTP delivery."""

import smtplib
import socket
import ssl
from dataclasses import dataclass
from email.headerregistry import Address
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from typing import Callable

from .models import MailRequest, normalized_address_key
from .providers import Provider, get_provider


class MailDeliveryError(RuntimeError):
    def __init__(self, code: str, message: str, refused: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.refused = refused


@dataclass(frozen=True, slots=True)
class SendResult:
    accepted: tuple[str, ...]
    refused: tuple[str, ...]

    @property
    def partial(self) -> bool:
        return bool(self.refused)


def build_message(request: MailRequest) -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = request.subject
    message["From"] = Address(
        display_name=request.sender_name,
        addr_spec=request.sender_email,
    )
    message["To"] = ", ".join(request.to)
    if request.cc:
        message["Cc"] = ", ".join(request.cc)
    if request.reply_to:
        message["Reply-To"] = request.reply_to
    message["Date"] = formatdate(localtime=True)
    message["Message-ID"] = make_msgid(domain=request.sender_email.rsplit("@", 1)[1])
    message.set_content(request.body, cte="quoted-printable")

    for attachment in request.attachments:
        maintype, subtype = attachment.content_type.split("/", 1)
        message.add_attachment(
            attachment.content,
            maintype=maintype,
            subtype=subtype,
            filename=attachment.filename,
        )
    return message


def send_email(
    request: MailRequest,
    *,
    provider_override: Provider | None = None,
    timeout: float = 30,
    smtp_factory: Callable[..., smtplib.SMTP] | None = None,
    smtp_ssl_factory: Callable[..., smtplib.SMTP_SSL] | None = None,
) -> SendResult:
    provider = provider_override or get_provider(request.provider_id)
    if provider_override is not None and provider_override.id != request.provider_id:
        raise MailDeliveryError(
            "provider_configuration", "The SMTP provider configuration does not match."
        )
    if provider is None or not provider.enabled:
        raise MailDeliveryError("provider_unavailable", "This provider is not available.")
    if provider.auth_method not in {"app_password", "password"}:
        raise MailDeliveryError(
            "provider_unavailable", "This provider requires an unsupported sign-in method."
        )

    smtp_factory = smtp_factory or smtplib.SMTP
    smtp_ssl_factory = smtp_ssl_factory or smtplib.SMTP_SSL
    context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_2

    client: smtplib.SMTP | smtplib.SMTP_SSL | None = None
    delivery_started = False
    result: SendResult | None = None
    try:
        if provider.security == "tls":
            client = smtp_ssl_factory(
                provider.smtp_host,
                provider.smtp_port,
                timeout=timeout,
                context=context,
            )
        elif provider.security == "starttls":
            client = smtp_factory(provider.smtp_host, provider.smtp_port, timeout=timeout)
            client.ehlo()
            client.starttls(context=context)
            client.ehlo()
        else:
            raise MailDeliveryError(
                "provider_configuration", "The provider has an invalid security configuration."
            )

        client.login(request.auth_username or request.sender_email, request.app_password)
        delivery_started = True
        refused_map = client.send_message(
            build_message(request),
            from_addr=request.sender_email,
            to_addrs=list(request.recipients),
        )
        delivery_started = False
        refused_keys = {normalized_address_key(address) for address in refused_map}
        refused = tuple(
            address
            for address in request.recipients
            if normalized_address_key(address) in refused_keys
        )
        accepted = tuple(
            address
            for address in request.recipients
            if normalized_address_key(address) not in refused_keys
        )
        result = SendResult(accepted=accepted, refused=refused)
    except MailDeliveryError:
        raise
    except smtplib.SMTPAuthenticationError as error:
        if _temporary_response(error.smtp_code):
            raise MailDeliveryError(
                "provider_temporary", "The provider temporarily refused authentication. Try again later."
            ) from None
        raise MailDeliveryError(
            "auth_failed",
            "The provider rejected the email address or app password.",
        ) from None
    except smtplib.SMTPRecipientsRefused as error:
        responses = tuple(error.recipients.values())
        if responses and all(_temporary_response(response[0]) for response in responses):
            raise MailDeliveryError(
                "provider_temporary",
                "The provider temporarily refused the recipients. Try again later.",
                tuple(error.recipients),
            ) from None
        raise MailDeliveryError(
            "recipients_refused",
            "The provider refused every recipient.",
            tuple(error.recipients),
        ) from None
    except smtplib.SMTPSenderRefused as error:
        if _temporary_response(error.smtp_code):
            raise MailDeliveryError(
                "provider_temporary", "The provider temporarily refused the sender. Try again later."
            ) from None
        raise MailDeliveryError(
            "sender_refused", "The provider did not allow this sender address."
        ) from None
    except smtplib.SMTPDataError as error:
        if _temporary_response(error.smtp_code):
            raise MailDeliveryError(
                "provider_temporary", "The provider temporarily refused the message. Try again later."
            ) from None
        raise MailDeliveryError(
            "provider_rejected", "The provider rejected the message content."
        ) from None
    except ssl.SSLCertVerificationError:
        raise MailDeliveryError(
            "tls_failed", "A secure connection to the provider could not be verified."
        ) from None
    except ssl.SSLError:
        if delivery_started:
            raise MailDeliveryError(
                "delivery_unknown",
                "The secure connection ended while sending. Check Sent Mail before trying again.",
            ) from None
        raise MailDeliveryError(
            "tls_failed", "A secure connection to the provider could not be established."
        ) from None
    except (socket.timeout, TimeoutError, smtplib.SMTPServerDisconnected):
        if delivery_started:
            raise MailDeliveryError(
                "delivery_unknown",
                "The connection ended while sending. Check Sent Mail before trying again.",
            ) from None
        raise MailDeliveryError(
            "connection_failed", "The email provider did not respond in time."
        ) from None
    except smtplib.SMTPResponseException as error:
        if _temporary_response(error.smtp_code):
            raise MailDeliveryError(
                "provider_temporary", "The provider is temporarily unavailable. Try again later."
            ) from None
        raise MailDeliveryError(
            "send_failed", "The email provider could not accept this message."
        ) from None
    except smtplib.SMTPException:
        if delivery_started:
            raise MailDeliveryError(
                "delivery_unknown",
                "The connection ended while sending. Check Sent Mail before trying again.",
            ) from None
        raise MailDeliveryError(
            "send_failed", "The email provider could not accept this message."
        ) from None
    except (socket.gaierror, ConnectionError, OSError):
        if delivery_started:
            raise MailDeliveryError(
                "delivery_unknown",
                "The connection ended while sending. Check Sent Mail before trying again.",
            ) from None
        raise MailDeliveryError(
            "connection_failed", "A secure connection to the email provider could not be made."
        ) from None
    finally:
        if client is not None:
            try:
                client.quit()
            except (OSError, smtplib.SMTPException):
                try:
                    client.close()
                except OSError:
                    pass

    if result is None:
        raise MailDeliveryError("send_failed", "The message could not be sent.")
    return result


def _temporary_response(code: int | str) -> bool:
    try:
        numeric_code = int(code)
    except (TypeError, ValueError):
        return False
    return 400 <= numeric_code < 500
