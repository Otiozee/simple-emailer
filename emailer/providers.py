"""Supported email-provider configuration."""

from dataclasses import asdict, dataclass
from types import MappingProxyType


@dataclass(frozen=True, slots=True)
class Provider:
    id: str
    name: str
    smtp_host: str
    smtp_port: int
    security: str
    auth_method: str
    enabled: bool
    help_url: str
    guidance: str
    unavailable_reason: str | None = None

    def public_data(self) -> dict[str, object]:
        data = asdict(self)
        data.pop("smtp_host")
        data.pop("smtp_port")
        data.pop("security")
        return data


PROVIDERS = MappingProxyType(
    {
        "gmail": Provider(
            id="gmail",
            name="Gmail",
            smtp_host="smtp.gmail.com",
            smtp_port=465,
            security="tls",
            auth_method="app_password",
            enabled=True,
            help_url="https://support.google.com/accounts/answer/185833",
            guidance="Use a 16-character app password from a Google Account with 2-Step Verification.",
        ),
        "yahoo": Provider(
            id="yahoo",
            name="Yahoo Mail",
            smtp_host="smtp.mail.yahoo.com",
            smtp_port=465,
            security="tls",
            auth_method="app_password",
            enabled=True,
            help_url="https://help.yahoo.com/kb/generate-manage-third-party-passwords-sln15241.html",
            guidance="Create a third-party app password in Yahoo Account Security.",
        ),
        "outlook": Provider(
            id="outlook",
            name="Outlook.com",
            smtp_host="smtp-mail.outlook.com",
            smtp_port=587,
            security="starttls",
            auth_method="oauth2",
            enabled=False,
            help_url="https://support.microsoft.com/en-us/office/pop-imap-and-smtp-settings-for-outlook-com-d088b986-291d-42b8-9564-9c414e2aa040",
            guidance="Microsoft requires Modern Auth/OAuth2 for Outlook.com SMTP.",
            unavailable_reason="OAuth2 setup requires a registered Microsoft application and is not available in this release.",
        ),
    }
)


def get_provider(provider_id: str) -> Provider | None:
    return PROVIDERS.get(provider_id)


def public_providers() -> list[dict[str, object]]:
    return [provider.public_data() for provider in PROVIDERS.values()]
