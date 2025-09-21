# Usage Guide

Your quick reference for day-to-day Steam Idle Bot commands. For a deeper dive, check the main README.

---

## 🔁 Everyday Commands

```bash
# Dry run – prints configuration, no login required
./run.sh --dry-run

# Start idling (Steam Guard challenge will appear if needed)
./run.sh

# Launch through UV without the helper script
uv run python -m steam_idle_bot --dry-run
```

---

## 🕹️ CLI Flags Cheat Sheet

| Flag | What it does |
| --- | --- |
| `--dry-run` | Preview games and settings without touching Steam |
| `--no-trading-cards` | Skip store lookups and accept the supplied game list |
| `--keep-completed-drops` | Include games that already exhausted their badge drops |
| `--max-games N` | Override the maximum number of concurrent games |
| `--config PATH` | Load configuration from a custom location |
| `--no-cache` | Ignore the on-disk trading-card cache for this run |
| `--max-checks N` | Stop store lookups after `N` successes (large libraries) |
| `--skip-failures` | Suppress non-timeout warnings while checking cards |

Combine flags to suit the session:

```bash
# Ignore card filters and idle the first ten games in your list
./run.sh --no-trading-cards --keep-completed-drops --max-games 10

# Cut down on API calls for massive libraries
./run.sh --max-checks 50 --skip-failures

# One-off dry-run without touching config.py
STEAM_USERNAME=foo STEAM_PASSWORD=bar ./run.sh --dry-run
```

---

## 📝 Configuration Reminders

- Copy `config_example.py` to `config.py` and fill in real credentials.
- Environment variables (`STEAM_USERNAME`, `STEAM_PASSWORD`, `STEAM_API_KEY`) override file values.
- `.env` files are supported; UV will load them automatically.

---

## 📚 More Resources

- Installation, architecture, and troubleshooting: see `README.md`.
