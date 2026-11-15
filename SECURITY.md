# Security

## Credential handling

Simple Emailer does not persist app passwords. A password exists temporarily in the CLI environment or hidden prompt, the browser request when using the web UI, the Python request object, and the SMTP authentication exchange. Application logs contain only HTTP request metadata and safe error messages.

Do not add credentials to source files, environment examples, URLs, analytics, crash reports, or tests. If a credential is ever committed or logged, revoke it at the provider rather than merely deleting the local copy.

The CLI deliberately has no password argument because command arguments can be exposed in shell history and process listings. Prefer its hidden prompt for interactive sends. Environment variables are useful for automation but may be readable by sufficiently privileged local processes.

## Local operation

The default loopback binding is the safest supported mode:

```bash
python3 -m emailer
```

Host-header and origin checks reduce browser-based attacks against the local API. Do not disable them. Malware, a hostile browser extension, or another process running as the same user remains outside the application's security boundary.

## Hosted operation

Hosted operation is intentionally disabled in this release. The built-in HTTP server accepts only loopback bindings and is not an internet-facing TLS terminator. Before adding a hosted deployment:

1. Put it behind a maintained HTTPS reverse proxy.
2. Add an explicit, narrowly scoped private service binding.
3. Add exact public-host and origin configuration.
4. Add authenticated user sessions and provider OAuth before general public access.
5. Add proxy-aware, distributed rate limits and attachment malware controls.
6. Prevent request-body logging at every proxy and monitoring layer.
7. Set short request timeouts and strict process/network egress policies.
8. Run each deployment with a dedicated unprivileged operating-system account.

The current in-memory rate limiter is defense in depth for local use, not sufficient public abuse prevention.

## Reporting

This repository has no public security contact yet. Until one is established, do not publish a newly discovered credential exposure or remotely exploitable issue with live secrets attached.
