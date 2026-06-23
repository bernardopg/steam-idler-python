---
layout: default
title: Usage Guide (EN)
---

# 📚 Usage Guide

Your quick reference for day-to-day Steam Idle Bot commands. For setup, configuration, and architecture, see the [full README](README.md).

---

## 🔁 Everyday commands

```bash
# Preview config + chosen games — no Steam contact, no login
./run.sh --dry-run

# Start idling (terminal). Steam Guard prompt appears if needed (python backend)
./run.sh

# Desktop GUI
./run-gui.sh

# Direct module entry (run.sh sets PYTHONPATH for you)
uv run python -m steam_idle_bot --dry-run
```

---

## 🕹️ CLI flags cheat sheet

| Flag | What it does |
| --- | --- |
| `--dry-run` | Preview games and settings without touching Steam |
| `--gui` | Launch the desktop GUI (same as `./run-gui.sh`) |
| `--no-trading-cards` | Skip card detection and accept the supplied game list |
| `--keep-completed-drops` | Include games that already exhausted their drops |
| `--max-games N` | Override the maximum number of concurrent games |
| `--config PATH` | Load configuration from a custom location |
| `--no-cache` | Ignore the on-disk caches for this run |
| `--max-checks N` | Stop card lookups after `N` checks (large libraries) |
| `--skip-failures` | Suppress non-timeout warnings while checking cards |

Combine flags to suit the session:

```bash
# Idle the first ten games regardless of card status
./run.sh --no-trading-cards --keep-completed-drops --max-games 10

# Cut down on API calls for massive libraries
./run.sh --max-checks 50 --skip-failures

# One-off dry-run with inline credentials
USERNAME=foo PASSWORD=bar ./run.sh --dry-run
```

---

## 📝 Configuration reminders

- **Preferred:** copy `.env.example` to `.env` and fill it in. **Never commit `.env`.**
- **Precedence:** CLI flags → environment variables → `.env` → defaults.
- **For accurate drop filtering** you need an authenticated `web:community` session. The easiest path: stay logged into Steam in your browser and keep `AUTO_BROWSER_COOKIES=true` (the default). See the [Authentication section](README.md#-authentication--card-drop-accuracy).
- A legacy `config.py` is still read if present, but is discouraged.

### Handy environment variables

| Variable | Quick note |
| --- | --- |
| `STEAM_API_KEY` | Enables library sync + badge data (recommended) |
| `IDLING_BACKEND` | `python` (Steam Guard / 2FA) or `steam_utility` |
| `AUTO_BROWSER_COOKIES` | Auto-recover a valid community session from your browser |
| `MAX_GAMES_TO_IDLE` | Cap concurrent games (Steam limit: 32) |
| `LOG_LEVEL` | `INFO` for clean output, `DEBUG` for troubleshooting |

---

## 📚 More resources

- Installation, architecture, authentication, and troubleshooting: [README.md](README.md)
- Security policy: [SECURITY.md](SECURITY.md)
