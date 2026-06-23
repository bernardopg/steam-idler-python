---
layout: default
title: Security Policy (EN)
---

# 🔒 Security Policy

## Supported versions

Active development happens on the `main` branch. Only the latest commit on `main` receives security updates.

## Reporting a vulnerability

Please report security issues **privately** via
[GitHub Security Advisories](https://github.com/bernardopg/steam-idler-python/security/advisories/new),
or email `security@steam-idle-bot.local` with:

- a clear description of the issue,
- steps to reproduce, and
- any proof-of-concept code or logs that demonstrate the impact (redact secrets).

Please **do not** open a public issue for vulnerabilities. We aim to acknowledge reports within 5 business days and will coordinate a fix and disclosure timeline with you.

## Handling Steam credentials & cookies

This bot uses real Steam credentials and **session cookies**, which are as sensitive as passwords. Treat them accordingly:

- `.env`, `config.py`, and `.cache/` are git-ignored — keep them local and never commit them.
- **Never paste cookies, tokens, or your API key** into issues, logs, or screenshots. When sharing logs for debugging, redact them.
- The bot only talks to official Steam endpoints over HTTPS; no data is sent anywhere else.
- `AUTO_BROWSER_COOKIES` reads cookies from your local browser only, on your machine. Nothing is uploaded.
- Prefer a dedicated/secondary Steam account, and rotate your Web API key if you suspect exposure.

## Known / accepted advisories

The `steam[client]` library (1.4.x) hard-requires `protobuf>=3.0,<4`. The protobuf
DoS advisories **GHSA-8qvm-5x2c-j2w7** and **GHSA-7gcm-g887-7qv7** are only patched in
protobuf `4.25.8` / `5.29.6`, which that library forbids — so they cannot be resolved
without dropping Steam support. They are accepted as **tolerable risk**: the bot only
deserializes protobuf/JSON from authenticated Steam servers over TLS, so the
denial-of-service vectors require untrusted input that never reaches it. The pin
rationale is documented in `pyproject.toml`.
