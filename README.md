# Steam Idle Bot

> Farm Steam playtime and trading cards without babysitting — complete with Steam Guard support, badge-awareness, and a modern Python toolchain.

[![CI](https://github.com/bernardopg/steam-idler-python/actions/workflows/ci.yml/badge.svg)](https://github.com/bernardopg/steam-idler-python/actions/workflows/ci.yml)

---

## ✨ Highlights

- 🎴 **Card-smart idling** — detect card-enabled games and skip any that already dropped every card (requires Steam Web API key).
- 🕹️ **Zero-maintenance library sync** — auto-pull your owned games and rotate the idled set every few minutes.
- 🔐 **Steam Guard friendly** — enter the 2FA code once and the session stays alive.
- 🧱 **Resilient networking** — retrying HTTP sessions, graceful fallbacks, and structured logging out of the box.
- ⚙️ **UV-first workflow** — blazing-fast installs, reproducible environments, and batteries-included developer tooling.

---

## 🚀 Quick Start (5 minutes)

1. **Install UV**

   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

2. **Clone & install**

   ```bash
   git clone https://github.com/bernardopg/steam-idler-python.git
   cd steam-idler-python
   uv sync
   ```

3. **Configure credentials**

   ```bash
   cp config_example.py config.py
   # Edit config.py with your Steam username, password, and optional API key
   ```

4. **Dry run sanity check**

   ```bash
   ./run.sh --dry-run
   ```

5. **Start idling**

   ```bash
   ./run.sh
   ```

> **Tip:** The badge-aware filter needs `STEAM_API_KEY`. Without it the bot still works, it just can’t tell if a game has drops remaining.

---

## 📦 Requirements

- Python **3.9+** (managed by UV).
- Steam account with games that drop cards.
- Steam Web API key *(recommended)* for badge progress filtering.

---

## ⚙️ Configuration Options

You can configure the bot via `config.py`, environment variables, or a `.env` file. Key settings are summarised below:

| Setting | Description | Default |
| --- | --- | --- |
| `USERNAME`, `PASSWORD` | Steam credentials (required) | – |
| `STEAM_API_KEY` | Enables owned-games lookups & badge filtering | `None` |
| `GAME_APP_IDS` | Fallback list when library can’t be fetched | `[570, 730]` |
| `FILTER_TRADING_CARDS` | Only idle games that have card support | `True` |
| `FILTER_COMPLETED_CARD_DROPS` | Skip games with zero cards remaining | `True` |
| `USE_OWNED_GAMES` | Pull the library from the Web API | `True` |
| `MAX_GAMES_TO_IDLE` | Steam caps simultaneous games at 32 | `30` |
| `LOG_LEVEL`, `LOG_FILE` | Logging verbosity and optional file output | `INFO`, `None` |
| `API_TIMEOUT`, `RATE_LIMIT_DELAY` | Store API timeouts & pacing | `10`, `0.5` |

Environment variable equivalents: `STEAM_USERNAME`, `STEAM_PASSWORD`, `STEAM_API_KEY`, etc. Dropping a `.env` file works too.

---

## ▶️ Running the Bot

```bash
# Dry run (no login) – prints config + chosen games
./run.sh --dry-run

# Normal run
./run.sh

# Bypass card filters for quick testing
./run.sh --keep-completed-drops --no-trading-cards

# Limit the session to five games
./run.sh --max-games 5

# One-off run with env vars only
STEAM_USERNAME=foo STEAM_PASSWORD=bar ./run.sh
```

You can also call the package directly:

```bash
uv run python -m steam_idle_bot --dry-run
```

### CLI Reference

| Flag | Purpose |
| --- | --- |
| `--dry-run` | Show configuration and chosen games without contacting Steam |
| `--no-trading-cards` | Skip store lookups and accept the supplied list |
| `--keep-completed-drops` | Include games even if badge drops are exhausted |
| `--max-games N` | Override `MAX_GAMES_TO_IDLE` |
| `--config PATH` | Load a custom configuration file |
| `--no-cache` | Disable the on-disk trading-card cache |
| `--max-checks N` | Cap store lookups for very large libraries |
| `--skip-failures` | Silence non-timeout errors while checking cards |

---

## 🧠 Under the Hood

1. **Library Discovery** — pulls owned games through `IPlayerService/GetOwnedGames` (falls back to `GAME_APP_IDS`).
2. **Card Detection** — fetches `appdetails` to verify category `29` and caches results on disk.
3. **Badge Awareness** — calls `IPlayerService/GetBadges` to drop games with `cards_remaining == 0`.
4. **Steam Session** — logs in via the official `steam` Python client, honouring Steam Guard challenges.
5. **Idle Loop** — refreshes the game list every ten minutes while keeping the gevent loop alive.

---

## 🔐 Security & Safety

- `config.py` is `.gitignore`d — never commit real credentials.
- Prefer a dedicated Steam account for idling to avoid impacting your main profile.
- Rotate your API key periodically; revoke it immediately if compromised.
- Logs respect `LOG_LEVEL`; set it to `DEBUG` for support, revert to `INFO` for day-to-day use.

---

## 🧪 Developer Guide

```text
steam-idle-bitter/
├── config_example.py
├── docs/
│   └── USAGE.md
├── run.sh
├── src/
│   └── steam_idle_bot/
│       ├── __main__.py
│       ├── __init__.py
│       ├── main.py
│       ├── config/
│       │   └── settings.py
│       ├── steam/
│       │   ├── badges.py
│       │   ├── client.py
│       │   ├── games.py
│       │   └── trading_cards.py
│       └── utils/
│           ├── exceptions.py
│           └── logger.py
├── tests/
│   ├── integration/
│   └── unit/
└── uv.lock
```

### Common Tasks

```bash
# Install dev extras and keep the lockfile fresh
uv sync --dev

# Run the full test suite
uv run pytest

# Lint & format
uv run ruff check .
uv run ruff format --check .

# Compile check (optional confidence boost)
uv run python -m compileall src/steam_idle_bot
```

Pull requests should include tests when behaviour changes, note any required config updates, and describe manual validation steps.

---

## 🛟 Troubleshooting

| Symptom | Fix |
| --- | --- |
| `Steam credentials not configured` | Ensure `config.py` exists or export `STEAM_USERNAME`/`STEAM_PASSWORD`. Placeholders like `your_steam_username` are rejected. |
| `Login failed` | Check Steam Guard for the 2FA code, confirm credentials, and verify the account isn’t locked. |
| `No games to idle` | Add a Steam Web API key, or run with `--no-trading-cards` to bypass filtering. |
| `ImportError: No module named 'steam'` | Run `uv sync`; if using system Python ensure it’s 3.9+. |
| Bot idles but no cards drop | The badge filter determined those games are exhausted. Run with `--keep-completed-drops` or expand `GAME_APP_IDS`. |

Enable verbose logging when debugging:

```bash
LOG_LEVEL=DEBUG ./run.sh --dry-run
```

---

## 📘 Further Reading

- [Usage cheatsheet](docs/USAGE.md)

---

## ⚖️ Responsible Use

This project is for educational purposes. Respect Steam’s Terms of Service and your regional regulations when using automated idlers.

Need help? Open an [issue](https://github.com/bernardopg/steam-idler-python/issues) with logs (redacting secrets) and steps to reproduce.
