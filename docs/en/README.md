# Steam Idle Bot

> 🚀 Automate Steam playtime farming and trading card drops effortlessly. No more manual babysitting – just set it up and let it run! With smart features like badge awareness, Steam Guard support, and a sleek Python setup, it's the ultimate tool for Steam enthusiasts.

[![CI Status](https://github.com/bernardopg/steam-idler-python/actions/workflows/ci.yml/badge.svg)](https://github.com/bernardopg/steam-idler-python/actions/workflows/ci.yml)
[![Python Version](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![GitHub Stars](https://img.shields.io/github/stars/bernardopg/steam-idler-python.svg?style=social)](https://github.com/bernardopg/steam-idler-python/stargazers)

---

## ✨ Why Choose Steam Idle Bot?

Tired of grinding for Steam trading cards and playtime? This bot handles it all intelligently and reliably. Whether you're boosting your badge collection or just accumulating hours, it's designed for zero hassle.

- 🎴 **Smart Card Idling**: Automatically detects games with trading cards and skips those you've fully farmed (needs a Steam Web API key for best results).
- 🕹️ **Auto-Library Sync**: Pulls your owned games on the fly and rotates them seamlessly – no manual updates required.
- 🔐 **Steam Guard Seamless**: Enter your 2FA code once, and the session stays active indefinitely.
- 🛡️ **Bulletproof Reliability**: Built-in retries, error handling, and logging keep things running smoothly through network hiccups.
- ⚡ **Modern Python Power**: Powered by UV for lightning-fast setup, reproducible environments, and dev-friendly tools.
- 📈 **Customizable & Efficient**: Fine-tune everything from game limits to logging, with support for massive libraries.

Perfect for gamers, collectors, or anyone looking to automate their Steam experience. Join the community and level up your profile effortlessly!

---

## 🚀 Quick Start (Under 5 Minutes)

Get up and running fast with these simple steps. We'll use UV for a hassle-free Python environment.

1. **Install UV** (if you don't have it):

   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

2. **Clone the Repo & Install Dependencies**:

   ```bash
   git clone https://github.com/bernardopg/steam-idler-python.git
   cd steam-idler-python
   uv sync
   ```

3. **Set Up Configuration**:

   ```bash
   cp config_example.py config.py
   # Open config.py in your editor and add your Steam username, password, and (optional) API key
   ```

4. **Test with a Dry Run**:

   ```bash
   ./run.sh --dry-run
   ```

   This previews your setup without logging in – great for sanity checks!

5. **Launch the Bot**:

   ```bash
   ./run.sh
   ```

   Enter your Steam Guard code if prompted, and watch it go!

> **Pro Tip**: Grab a free Steam Web API key from [Steam's developer portal](https://steamcommunity.com/dev/apikey) to unlock advanced features like badge filtering. Without it, the bot still works but idles everything indiscriminately.

---

## 📦 Requirements

- **Python**: 3.9 or higher (UV handles this for you).
- **Steam Account**: With games that support trading cards.
- **Steam Web API Key** (recommended): For library syncing and smart filtering.
- **Optional**: A dedicated Steam account to avoid disrupting your main profile.

No other dependencies – UV takes care of the rest!

---

## ⚙️ Configuration Made Easy

Customize via `config.py`, environment variables, or a `.env` file. Environment vars override file settings for flexibility.

| Setting                  | Description                                                                 | Default        |
|--------------------------|-----------------------------------------------------------------------------|----------------|
| `USERNAME`, `PASSWORD`   | Your Steam login credentials (required).                                    | –              |
| `STEAM_API_KEY`          | Unlocks library fetching and badge progress checks.                         | `None`         |
| `GAME_APP_IDS`           | Fallback game list if API key is missing (e.g., [570, 730] for Dota 2/CS:GO). | `[570, 730]`   |
| `FILTER_TRADING_CARDS`   | Only idle games with trading card support.                                  | `True`         |
| `FILTER_COMPLETED_CARD_DROPS` | Skip games where all cards have dropped.                               | `True`         |
| `USE_OWNED_GAMES`        | Auto-fetch your full game library via API.                                  | `True`         |
| `MAX_GAMES_TO_IDLE`      | Max simultaneous games (Steam limit: 32).                                   | `30`           |
| `LOG_LEVEL`, `LOG_FILE`  | Logging detail and optional file output.                                    | `INFO`, `None` |
| `API_TIMEOUT`, `RATE_LIMIT_DELAY` | API request timeouts and delays to avoid rate limits.              | `10`, `0.5`    |

**Examples**:

- Environment vars: `export STEAM_USERNAME=yourname STEAM_PASSWORD=yourpass`
- .env file: Create `.env` with `STEAM_USERNAME=yourname` etc., and UV loads it automatically.

---

## ▶️ Running the Bot

Use the handy `run.sh` script or call the package directly. Here's your command toolkit:

```bash
# Preview without logging in
./run.sh --dry-run

# Full launch
./run.sh

# Ignore filters for testing (idle everything)
./run.sh --keep-completed-drops --no-trading-cards

# Limit to 10 games
./run.sh --max-games 10

# Direct UV run
uv run python -m steam_idle_bot --dry-run
```

### CLI Flags Reference

| Flag                | Purpose                                                                 |
|---------------------|-------------------------------------------------------------------------|
| `--dry-run`        | Simulate and print config/games without Steam interaction.              |
| `--no-trading-cards` | Bypass card checks and use the raw game list.                          |
| `--keep-completed-drops` | Include fully farmed games.                                        |
| `--max-games N`     | Set max concurrent games.                                               |
| `--config PATH`     | Use a custom config file.                                               |
| `--no-cache`        | Disable disk caching for card data.                                     |
| `--max-checks N`    | Limit API calls for huge libraries.                                     |
| `--skip-failures`   | Quietly ignore non-critical errors during checks.                       |

Mix and match for your needs!

---

## 🧠 How It Works (Under the Hood)

1. **Library Fetch**: Grabs your owned games via Steam's API (or falls back to defaults).
2. **Card Scanning**: Checks for trading card support and caches results locally.
3. **Badge Smartness**: Queries badge progress to skip exhausted games.
4. **Secure Login**: Uses the official Steam Python client with Steam Guard handling.
5. **Idle Cycle**: Rotates games every 10 minutes in an efficient loop.

It's all powered by gevent for async efficiency and resilient HTTP sessions.

---

## 🔐 Security & Best Practices

- **Credential Safety**: `config.py` is git-ignored – keep it local!
- **Dedicated Account**: Use a secondary Steam profile to protect your main one.
- **API Key Management**: Revoke and rotate if needed; get yours in [Steam's developer portal](https://steamcommunity.com/dev/apikey).
- **Logging**: Stick to `INFO` for normal use; bump to `DEBUG` for troubleshooting.
- **Privacy**: The bot only interacts with Steam APIs – no data leaves your machine.

For vulnerabilities, see our [Security Policy](../SECURITY.md).

---

## 🧪 Developer Guide

Contribute to make it even better! Project structure:

```text
steam-idle-bot/
├── config_example.py
├── docs/
│   └── USAGE.md
├── run.sh
├── src/
│   └── steam_idle_bot/
│       ├── __main__.py
│       ├── config/
│       ├── steam/
│       └── utils/
├── tests/
└── uv.lock
```

**Dev Commands**:

```bash
# Sync dev dependencies
uv sync --dev

# Run tests
uv run pytest

# Lint & format
uv run ruff check .
uv run ruff format .

# Type check
uv run mypy src/
```

PRs welcome! Include tests, update docs, and describe changes.

---

## 🛟 Troubleshooting

| Issue                          | Solution                                                                 |
|--------------------------------|--------------------------------------------------------------------------|
| Credentials not configured     | Fill `config.py` or set env vars; avoid placeholders.                    |
| Login failed                   | Verify creds/2FA; check for account locks.                               |
| No games to idle               | Add API key or use `--no-trading-cards`.                                 |
| Import errors                  | Run `uv sync`; ensure Python 3.9+.                                       |
| No cards dropping              | Check filters; try `--keep-completed-drops`.                             |

For more, enable `LOG_LEVEL=DEBUG` and file an [issue](https://github.com/bernardopg/steam-idler-python/issues) with redacted logs.

---

## 📘 Resources & Community

- [Usage Cheatsheet](USAGE.md)
- [GitHub Repo](https://github.com/bernardopg/steam-idler-python)
- [Report Issues](https://github.com/bernardopg/steam-idler-python/issues)
- Star the repo if you love it! ⭐

---

## ⚖️ Responsible Use & License

This tool is for educational and personal use. Always follow Steam's ToS and local laws. Not affiliated with Valve.

Licensed under MIT – fork, modify, and enjoy!

---

## Security Policy

**Supported Versions**: Latest `main` branch only.

**Report Vulnerabilities**: Email <noreply@scalpel.com.br> with details. No public issues, please. We respond within 5 business days. PGP optional – share your key for encrypted replies.
