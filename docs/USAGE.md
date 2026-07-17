# Usage Guide

> This page is kept for compatibility. The maintained guides live at
> [`docs/en/USAGE.md`](en/USAGE.md) and [`docs/pt-br/USAGE.md`](pt-br/USAGE.md).

Your quick reference for day-to-day Steam Idle Bot commands. For setup,
configuration, and architecture, see the [English README](en/README.md).

---

## 🔁 Everyday commands

```bash
# Preview config + chosen games — no Steam contact, no login
./run.sh --dry-run

# Start idling (terminal). Steam Guard prompt appears if needed
./run.sh

# Desktop GUI
./run-web.sh

# Direct module entry
uv run python -m steam_idle_bot --dry-run
```

---

## 🕹️ CLI flags cheat sheet

| Flag | What it does |
| --- | --- |
| `--dry-run` | Preview games and settings without touching Steam |
| `--gui` | Deprecated: launches the web UI (`--web`) |
| `--no-trading-cards` | Skip card detection and accept the supplied game list |
| `--keep-completed-drops` | Include games that already exhausted their drops |
| `--max-games N` | Override the maximum number of concurrent games |
| `--refresh-interval-seconds N` | Re-run selection every `N` seconds; refreshes use quiet logging and short-lived caches |
| `--duration-minutes N` | Stop idling automatically after `N` minutes |
| `--post-run-verify-seconds N` | Re-scrape counts/inventory after stopping to catch Steam badge lag |
| `--config PATH` | Load configuration from a custom location |
| `--no-cache` | Ignore the on-disk caches for this run |
| `--max-checks N` | Stop card lookups after `N` checks (large libraries) |
| `--skip-failures` | Suppress non-timeout warnings while checking cards |

---

## 📝 Configuration reminders

- **Preferred:** copy `.env.example` to `.env` and fill it in. **Never commit `.env`.**
- **Precedence:** CLI flags → environment variables → `.env` → defaults.
- For accurate drop filtering, keep `AUTO_BROWSER_COOKIES=true` and stay logged
  into Steam in your browser — see the README's Authentication section.
- Refreshes are optimized with short in-memory caches and inventory-based
  rotation when a game has dropped all known remaining cards.
- `./run.sh` writes bot output to `logs/runs/run_*.log`, keeps Python out of a
  shell pipeline so Ctrl+C works, and supports `STEAM_IDLE_SKIP_SYNC=1`,
  `STEAM_IDLE_RUNNER_VERBOSE=1`, and `STEAM_IDLE_PRESERVE_ENV=1` for runner
  behavior.
- A legacy `config.py` is still read if present, but is discouraged.

---

## 📚 More resources

- Full guides: [English](en/README.md) · [Português (BR)](pt-br/README.md)
