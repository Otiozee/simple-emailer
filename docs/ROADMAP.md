# Product Roadmap

## Current: secure local MVP

- Gmail and Yahoo provider presets
- Verified TLS and app-password authentication
- To, Cc, Bcc, Reply-To, plain-text body, and bounded attachments
- Responsive installable PWA
- Deliberate review and confirmation before delivery
- Local-only defaults and offline unit tests

## Next: OAuth and deployment boundary

1. Register separate OAuth clients for development and production.
2. Add authorization-code flow with PKCE for Google and Microsoft.
3. Store refresh tokens only in an operating-system credential vault for native targets.
4. For the hosted web target, encrypt refresh tokens with managed keys and add authenticated sessions.
5. Add token revocation, account disconnect, privacy policy, and provider verification.
6. Replace app-password prompts with OAuth where providers support it.

OAuth client identifiers, redirect URIs, consent-screen ownership, and production domains are product decisions and cannot be safely hard-coded before those accounts exist.

## Packaging

1. Keep the web UI and API contract shared across targets.
2. Add an Android wrapper only after OAuth works without exposing a reusable client secret.
3. Add Linux packages and a Windows installer around a loopback service and embedded web view.
4. Sign every binary and publish checksums.
5. Build Android, Linux, and Windows artifacts in isolated CI runners.
6. Run accessibility, responsive-layout, provider sandbox, and clean-machine installer tests before release.

## Production hardening

- User authentication and account ownership checks
- Distributed abuse limits and delivery audit events without message content
- Provider-specific quota and error guidance
- Attachment malware scanning for hosted delivery
- Structured, redacted observability
- Privacy, retention, acceptable-use, and incident-response policies
- OAuth-first HTML composer with explicit sanitization and previews
