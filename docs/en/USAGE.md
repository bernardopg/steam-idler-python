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
| `--refresh-interval-seconds N` | Re-run selection every `N` seconds; refreshes use quiet logging and short-lived caches |
| `--checkpoint-minutes N` | Write JSON/Markdown progress checkpoints every `N` minutes |
| `--duration-minutes N` | Stop idling automatically after `N` minutes |
| `--post-run-verify-seconds N` | Re-scrape counts/inventory after stopping to catch Steam badge lag |
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

# Timed farm with quicker rotation opportunities and final badge/inventory verification
./run.sh --duration-minutes 30 --refresh-interval-seconds 120 --post-run-verify-seconds 30

# Runner controls: faster startup during development, or verbose environment sync
STEAM_IDLE_SKIP_SYNC=1 ./run.sh --dry-run
STEAM_IDLE_RUNNER_VERBOSE=1 ./run.sh

# One-off dry-run with inline credentials
USERNAME=foo PASSWORD=bar ./run.sh --dry-run
```

---

## 📝 Configuration reminders

- **Preferred:** copy `.env.example` to `.env` and fill it in. **Never commit `.env`.**
- **Precedence:** CLI flags → environment variables → `.env` → defaults.
- **For accurate drop filtering** you need an authenticated `web:community` session. The easiest path: stay logged into Steam in your browser and keep `AUTO_BROWSER_COOKIES=true` (the default). See the [Authentication section](README.md#-authentication--card-drop-accuracy).
- Refreshes are optimized: badge payloads and positive drop verdicts are cached briefly in memory, and inventory snapshots can rotate out a game whose known remaining cards have all dropped before badge pages catch up.
- A legacy `config.py` is still read if present, but is discouraged.

### Handy environment variables

| Variable | Quick note |
| --- | --- |
| `STEAM_API_KEY` | Enables library sync + badge data (recommended) |
| `IDLING_BACKEND` | `python` (Steam Guard / 2FA) or `steam_utility` |
| `AUTO_BROWSER_COOKIES` | Auto-recover a valid community session from your browser |
| `MAX_GAMES_TO_IDLE` | Cap concurrent games (Steam limit: 32) |
| `LOG_LEVEL` | `INFO` for clean output, `DEBUG` for troubleshooting |
| `STEAM_IDLE_SKIP_SYNC` | Set to `1` to skip the runner's preflight `uv sync` |
| `STEAM_IDLE_RUNNER_VERBOSE` | Set to `1` to show `uv sync` output while `./run.sh` prepares the environment |
| `STEAM_IDLE_PRESERVE_ENV` | Set to `1` when exported variables should intentionally override `.env` |

---

## 📚 More resources

- Installation, architecture, authentication, and troubleshooting: [README.md](README.md)
- Security policy: [SECURITY.md](SECURITY.md)
