---
layout: default
title: Steam Idle Bot (EN)
---

# 🎴 Steam Idle Bot

> Farm Steam playtime and trading-card drops on autopilot — accurately, efficiently, and without babysitting.

[![Python](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Stars](https://img.shields.io/github/stars/bernardopg/steam-idler-python.svg?style=social)](https://github.com/bernardopg/steam-idler-python/stargazers)

---

## ✨ Why Steam Idle Bot?

Most idlers blindly run every game in your library. This one is **selective and accurate**:

- 🎴 **Targeted idling** — detects which games have trading cards and how many drops remain, then idles only those.
- 🧠 **Gets faster every run** — persistent no-drop caches skip fully farmed games, while short-lived in-session caches avoid re-scraping games that were just confirmed to still have drops.
- 🔐 **Trustworthy verdicts** — before relying on a Steam web session, the bot *verifies it's actually logged in*. A logged-out/expired session is detected and reported instead of silently idling drained games.
- 🪄 **Self-healing auth** — if your configured cookies aren't a valid community session, it can pull a fresh one from a browser you're already signed into Steam with.
- 🖥️ **Readable terminal UI** — a live panel with game names, cards remaining, and idle time, plus a full session report when you stop.
- 🔁 **Two backends** — the built-in Python Steam client (handles Steam Guard / 2FA) or delegation to a local `steam-utility` install, with automatic fallback.
- 🔄 **Rotates mid-session** — inventory snapshots can prove a game dropped all known remaining cards before badge pages update, so the next refresh can swap it out.
- ⚡ **Modern & tested** — `uv`-managed, reproducible environments, full test suite, type-checked.

---

## 🚀 Quick Start (under 5 minutes)

1. **Install [uv](https://docs.astral.sh/uv/)** (if you don't have it):

   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

2. **Clone & install:**

   ```bash
   git clone https://github.com/bernardopg/steam-idler-python.git
   cd steam-idler-python
   uv sync
   ```

3. **Configure:**

   ```bash
   cp .env.example .env
   # Edit .env — set USERNAME, PASSWORD, and ideally STEAM_API_KEY
   ```

4. **Preview (no Steam contact):**

   ```bash
   ./run.sh --dry-run
   ```

5. **Run:**

   ```bash
   ./run.sh          # terminal
   ```

   Enter your Steam Guard code if prompted (Python backend only).

> 💡 **Get an API key.** A free [Steam Web API key](https://steamcommunity.com/dev/apikey) enables automatic library sync and badge-based drop filtering. Without it, the bot falls back to your manual `GAME_APP_IDS` list.

---

## 📦 Requirements

- **Python 3.12+** — `uv` installs and manages it for you.
- **A Steam account** with games that support trading cards.
- **Steam Web API key** *(recommended)* — for library sync and badge progress.
- **An authenticated web session** *(for drop filtering)* — see [Authentication & card-drop accuracy](#-authentication--card-drop-accuracy).
- *(Optional)* a dedicated/secondary Steam account.

---

## ⚙️ Configuration

Settings load from environment variables and a `.env` file (copy `.env.example`). Precedence: **CLI flags → environment variables → `.env` → defaults**. A legacy `config.py` is also read if present, but `.env` is the recommended path.

### Core

| Variable | Description | Default |
| --- | --- | --- |
| `USERNAME`, `PASSWORD` | Steam login credentials **(required)**. | – |
| `STEAM_API_KEY` | Unlocks library sync and badge progress. | _(none)_ |
| `USE_OWNED_GAMES` | Auto-fetch your full library via the API. | `true` |
| `GAME_APP_IDS` | Manual game list (JSON `[570,730]` or CSV `570,730`) used when not syncing owned games. | `[570,730]` |
| `EXCLUDE_APP_IDS` | App IDs to always skip. | `[]` |
| `MAX_GAMES_TO_IDLE` | Max simultaneous games (Steam hard limit: 32). | `30` |
| `FILTER_TRADING_CARDS` | Only idle games that have trading cards. | `true` |
| `FILTER_COMPLETED_CARD_DROPS` | Skip games whose drops are exhausted. | `true` |

### Idling backend

| Variable | Description | Default |
| --- | --- | --- |
| `IDLING_BACKEND` | `python` (built-in `steam` client) or `steam_utility` (delegate to a local install). | `python` |
| `STEAM_UTILITY_PATH` | Path to a local `steam-utility-multiplataform` checkout (auto-discovered in sibling dirs if empty). | _(auto)_ |

The Python backend handles Steam Guard / 2FA and builds an authenticated web session. If it fails to initialize, log in, start, or reconnect, the bot **automatically falls back** to the `steam_utility` backend.

### Authentication & cookies

| Variable | Description | Default |
| --- | --- | --- |
| `STEAM_WEB_COOKIES` | Authenticated cookies for community scraping. Accepts a JSON object, a browser-export JSON array, or `k=v; k=v`. | `{}` |
| `AUTO_BROWSER_COOKIES` | If the configured session isn't a valid community login, recover cookies from a locally logged-in browser. | `true` |
| `BROWSER_COOKIES_BROWSER` | Which browser to read from: `auto`, `chrome`, `firefox`, `edge`, `brave`, `chromium`, `opera`, `vivaldi`, `librewolf`. | `auto` |

### Caches

| Variable | Description | Default |
| --- | --- | --- |
| `ENABLE_CARD_CACHE` | Master switch for both on-disk caches. | `true` |
| `CARD_CACHE_PATH` | "Has trading cards" cache. | `.cache/trading_cards.json` |
| `CARD_CACHE_TTL_DAYS` | TTL for the trading-card cache. | `30` |
| `DROP_CACHE_PATH` | "No drops remaining" cache (per account). | `.cache/no_drop_cards.json` |
| `DROP_CACHE_TTL_DAYS` | TTL for the no-drop cache. | `90` |

### Logging & performance

| Variable | Description | Default |
| --- | --- | --- |
| `LOG_LEVEL` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`. Use `INFO` for clean output. | `INFO` |
| `LOG_FILE` | Optional log file path. | _(none)_ |
| `API_TIMEOUT` | Per-request timeout (seconds). | `10` |
| `RATE_LIMIT_DELAY` | Base delay between API calls; auto-increases on HTTP 429. Raise for huge libraries. | `1.0` |
| `MAX_CHECKS` | Cap the number of trading-card lookups (perf tuning). | _(none)_ |
| `SKIP_FAILURES` | Suppress non-timeout errors during card checks. | `false` |

---

## 🔐 Authentication & card-drop accuracy

Filtering out games with **no remaining drops** requires reading your authenticated Steam community badge pages. This is the single most important thing to get right — otherwise the bot idles games that have nothing left to drop.

**The catch:** the `steamLoginSecure` cookie is *audience-scoped*. A token copied from `store.steampowered.com` has audience `web:store` and is **rejected** by `steamcommunity.com` — pages load logged-out, every game looks ambiguous, and filtering becomes meaningless. You need a **`web:community`** token.

The bot defends against this automatically:

1. **Session verification** — before trusting any verdict, it probes a community page to confirm you're actually logged in. If not, it logs a clear warning and stays conservative (excludes unknowns) instead of idling drained games.
2. **Browser recovery** — with `AUTO_BROWSER_COOKIES=true` (default), it pulls a valid `web:community` session straight from a browser you're signed into Steam with. Because community tokens are short-lived, this keeps the bot self-healing across runs.

**Your options, simplest first:**

- ✅ **Stay logged into Steam in your browser** and leave `AUTO_BROWSER_COOKIES=true`. Nothing else to do.
- 🔑 **Use the Python backend** (`IDLING_BACKEND=python`): logging in once (with 2FA) mints a proper community session.
- 📋 **Paste cookies manually** into `STEAM_WEB_COOKIES` — make sure they come from `steamcommunity.com`, not the store.

> ℹ️ If the badge API reports no `cards_remaining` (common once all your badges are completed), the bot reads the count directly from the badge page so the panel and report still show real numbers.

---

## ▶️ Running the bot

```bash
./run.sh --dry-run                         # preview config + chosen games, no Steam contact
./run.sh                                   # normal run (terminal)
./run.sh --max-games 10                    # cap idled games
./run.sh --no-trading-cards                # skip card filtering (idle the raw list)
./run.sh --keep-completed-drops            # include fully-farmed games
STEAM_IDLE_SKIP_SYNC=1 ./run.sh            # skip the runner's preflight uv sync
STEAM_IDLE_RUNNER_VERBOSE=1 ./run.sh       # show uv sync output while preparing
uv run python -m steam_idle_bot --dry-run  # direct module entry
```

The terminal runner prints a compact banner, writes bot output to `logs/runs/run_*.log`, and keeps Python out of a shell pipeline so `Ctrl+C` reaches the bot directly. Normal runs clear stale exported Steam Idle Bot environment overrides so `.env` wins; set `STEAM_IDLE_PRESERVE_ENV=1` when exported variables are intentional.

### CLI flags

| Flag | Purpose |
| --- | --- |
| `--dry-run` | Print config and chosen games without contacting Steam. |
| `--gui` | Deprecated: launches the web UI (`--web`). |
| `--no-trading-cards` | Skip card detection; use the raw game list. |
| `--keep-completed-drops` | Include games that already exhausted their drops. |
| `--max-games N` | Override max concurrent games. |
| `--config PATH` | Load a custom configuration file. |
| `--no-cache` | Disable the on-disk caches for this run. |
| `--max-checks N` | Cap trading-card lookups (large libraries). |
| `--skip-failures` | Suppress non-timeout warnings during checks. |

See the [Usage Guide](USAGE.md) for combined-flag recipes.

---

## 🧠 How it works

```text
owned games ─▶ has trading cards? ─▶ drops remaining? ─▶ exclusions ─▶ idle (max 32)
                 (badge catalog            (badge API or       (config +
                  + store API,              authenticated        session-drained)
                  cached)                   scraping, cached)
```

1. **Library** — fetched via the Steam Web API (with names), or your manual list.
2. **Has cards** — resolved from the badge catalog, with a store-API fallback; store results are cached on disk and badge payloads are cached briefly in memory.
3. **Drops remaining** — preferred from the badge API; when it lacks data, falls back to authenticated community-page scraping. Games confirmed *without* drops are cached and skipped on future runs; games recently confirmed *with* drops are trusted for a short in-session window to avoid redundant refresh traffic.
4. **Idle loop** — starts idling, then re-runs the pipeline every `REFRESH_INTERVAL_SECONDS`, reconnecting (and failing over backends) as needed. Each refresh also compares current inventory to the pre-run snapshot; when inventory-confirmed drops equal all known remaining cards for a game, that app is excluded from the next selection so another candidate can take its slot even if Steam badge pages lag.

For a deeper architectural map, see [`CLAUDE.md`](../../CLAUDE.md) in the repo root.

---

## 🖥️ What you'll see

A live panel while idling:

```text
🎮 Steam Idle Bot — em idle agora
┌───┬─────────┬───────────────────────┬──────────────────┬────────────┐
│ # │ App ID  │ Jogo                  │ Cartas restantes │ Tempo idle │
├───┼─────────┼───────────────────────┼──────────────────┼────────────┤
│ 1 │  391540 │ Undertale             │                3 │      0 min │
│ 2 │  362890 │ Black Mesa            │                2 │      0 min │
└───┴─────────┴───────────────────────┴──────────────────┴────────────┘
18 games idling • cards remaining: 51 • session: 0 min
```

> Tip: run with `LOG_LEVEL=INFO` (the default) for this clean view. `DEBUG` adds verbose per-game lines, useful only for troubleshooting.

The final session report now shows a drop **Source**. `remaining-count` means before/after badge-page counts decreased; `inventory` means Steam inventory proved a new card even if badge pages lagged; `count+inventory` means both sources agreed. When you see `Cards: 3 → 3` with an inventory-confirmed drop, the report explains that the badge/scraper count lagged and inventory was used for the total.

---

## 🛟 Troubleshooting

| Symptom | Fix |
| --- | --- |
| `Missing credentials` | Set `USERNAME`/`PASSWORD` in `.env` (no placeholder values). |
| Login failed | Check credentials/2FA; confirm the account isn't locked. |
| "NOT authenticated against steamcommunity" warning | Your session is store-only/expired. Stay logged into Steam in a browser (with `AUTO_BROWSER_COOKIES=true`), use `IDLING_BACKEND=python`, or paste community cookies. See [Authentication](#-authentication--card-drop-accuracy). |
| Idles drained games / misses real ones | Same root cause as above — the session isn't a valid community login. |
| "Cards remaining" shows `?` | The badge API has no `cards_remaining` for a fully-completed profile; counts are read from badge pages when the session is authenticated. |
| No games to idle | Add an API key, or run `--no-trading-cards` / `--keep-completed-drops`. |
| First run is slow | Expected — it scans the whole library once, then caches. Later runs are fast. |
| Import errors | Run `uv sync`; ensure Python 3.12+. |

For deeper diagnosis, set `LOG_LEVEL=DEBUG` and open an [issue](https://github.com/bernardopg/steam-idler-python/issues) with **redacted** logs (never paste cookies, tokens, or your API key).

---

## 🧪 Developer guide

```text
steam-idler-python/
├── .env.example
├── run.sh / run-web.sh
├── pyproject.toml / uv.lock
├── src/steam_idle_bot/
│   ├── __main__.py        # entry point
│   ├── main.py            # SteamIdleBot orchestrator
│   ├── config/            # Pydantic settings
│   ├── steam/             # backends + card/badge/cookie services
│   └── utils/             # logging, tracker, exceptions
├── tests/
└── docs/
```

```bash
uv sync --dev                 # install dev deps
uv run pytest -q              # run tests
uv run pytest -q --cov=src/steam_idle_bot --cov-report=term-missing
uv run ruff check .           # lint
uv run ruff format .          # format
uv run mypy src               # type-check
```

CI runs the suite on Python 3.12–3.14. PRs welcome — include tests, update docs, and describe your changes. Enable the pre-commit guard with `git config core.hooksPath .githooks` (it blocks committing `config.py` and cache/venv files).

---

## 🔒 Security

- **Never commit secrets.** `.env`, `config.py`, and `.cache/` are git-ignored. Keep your API key and cookies local.
- Steam cookies are credentials — treat them like passwords.
- Prefer a dedicated/secondary Steam account.
- Vulnerability reporting and accepted-advisory notes: [SECURITY.md](SECURITY.md).

---

## ⚖️ Responsible use & license

For educational and personal use. Follow Steam's Terms of Service and your local laws. Not affiliated with Valve. Licensed under [MIT](LICENSE).

---

## 📘 Resources

- [Usage cheatsheet](USAGE.md) · [Security policy](SECURITY.md)
- [GitHub repository](https://github.com/bernardopg/steam-idler-python) · [Report an issue](https://github.com/bernardopg/steam-idler-python/issues)
- Enjoying it? Star the repo ⭐
