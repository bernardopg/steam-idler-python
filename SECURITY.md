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
- `.env` is written with owner-only permissions (`0600`). If you created it by hand, run `chmod 600 .env`.
- The `native` backend keeps a Steam **refresh token** in `NATIVE_SESSION_PATH` (`.cache/steam_native_session.json`, mode `0600`, git-ignored). It logs into your account without the password or Steam Guard for months, so guard it like the password. To revoke it, delete the file and remove the "Steam Idle Bot" device under Steam → Account details → Authorized devices; changing the password also revokes it.

## Web UI exposure

The web UI (`--web`) has **no login**. It is meant to be opened only on the machine running the bot:

- It binds to `127.0.0.1` and only answers requests whose `Host` is a loopback name, which blocks DNS-rebinding attacks from websites you visit.
- Changes (start/stop, settings, Steam Guard codes) and the live WebSocket refuse requests from other origins (CSRF / cross-site WebSocket hijacking).
- Secrets (password, Web API key, session cookies) are never sent back to the browser; they are shown masked.

Do not expose the port to a network or the internet (port-forwarding, `0.0.0.0` binds, public tunnels). To reach it remotely, use an SSH tunnel: `ssh -L 8765:127.0.0.1:8765 host`.

## Known / accepted advisories

The `steam[client]` library (1.4.x) hard-requires `protobuf>=3.0,<4`. The protobuf
DoS advisories **GHSA-8qvm-5x2c-j2w7** and **GHSA-7gcm-g887-7qv7** are only patched in
protobuf `4.25.8` / `5.29.6`, which that library forbids — so they cannot be resolved
while the legacy `python` backend is installed. The `native` backend does not use
protobuf at all (it ships its own minimal codec), so it is the path to dropping both. They are accepted as **tolerable risk**: the bot only
deserializes protobuf/JSON from authenticated Steam servers over TLS, so the
denial-of-service vectors require untrusted input that never reaches it. The pin
rationale is documented in `pyproject.toml`.

---

Localized copies: [English](docs/en/SECURITY.md) · [Português (BR)](docs/pt-br/SECURITY.md)
