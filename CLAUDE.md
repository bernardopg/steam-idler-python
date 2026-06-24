# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Steam Idle Bot — automates Steam playtime farming and trading-card drops. Python package `steam_idle_bot` under a `src/` layout, managed with `uv`. Runs as a terminal workflow or a Tkinter GUI.

## Commands

All commands run through `uv` (it auto-syncs the environment).

```bash
# Run the bot (terminal). Wraps `uv sync` + `python -m steam_idle_bot`, tees output to logs/runs/
./run.sh
./run.sh --dry-run              # print config + chosen games, no Steam contact
./run.sh --no-trading-cards     # skip trading-card filtering
./run.sh --max-games 10         # cap idled games
./run-gui.sh                    # launch the Tkinter GUI (== python -m steam_idle_bot --gui)

# Direct module entry (needs src/ on PYTHONPATH, which run.sh sets)
uv run python -m steam_idle_bot [args]

# Tests
uv run pytest -q                                         # full suite
uv run pytest -q tests/unit/test_games.py               # single file
uv run pytest -q tests/unit/test_games.py::test_name    # single test
uv run pytest -q --cov=src/steam_idle_bot --cov-report=term-missing   # with coverage (CI form uses --cov-report=xml)

# Lint & types
uv run ruff check .             # lint (line-length 250; rules E,F,I,UP,B,SIM,W)
uv run ruff format .            # format
uv run mypy src                 # type-check (mypy_path=src, ignore_missing_imports)
```

CI (`.github/workflows/ci.yml`) runs pytest+coverage across Python 3.12–3.14 on push/PR to `main`, matching `requires-python = ">=3.12"`. Tests inject `USERNAME=test_user` / `PASSWORD=test_pass` via env so the `Settings` model validates.

A `.githooks/pre-commit` (enable with `git config core.hooksPath .githooks`) blocks committing `config.py` and staged cache/venv/.vscode files.

## Configuration

`Settings` (`config/settings.py`) is a Pydantic-v2 `BaseSettings`. Credentials and options come from environment / `.env` (copy `.env.example`). `USERNAME` and `PASSWORD` are required; placeholder values are rejected by a validator.

- Config precedence (`settings_customise_sources`): init kwargs → env vars → `.env` → secrets. Custom `FlexibleEnvSettingsSource` / `FlexibleDotEnvSettingsSource` tolerantly parse list fields (`GAME_APP_IDS`, `EXCLUDE_APP_IDS` accept JSON `[570,730]` or CSV `570,730`) and the cookie map (`STEAM_WEB_COOKIES` accepts JSON object, browser-export JSON array, or `k=v; k=v`).
- `Settings.load_from_file()` also imports a legacy `config.py` if present, mapping its UPPER_CASE names to settings fields.
- `save_to_env_file()` serializes settings back to `.env` — used by the GUI to persist user changes.
- CLI flags in `main.py` override loaded settings (`--max-games`, `--no-cache`, `--max-checks`, `--skip-failures`, `--keep-completed-drops`, `--no-trading-cards`).
- **Web session auth**: card-drop scraping needs a `web:community` `steamLoginSecure` (see [[steam-web-cookies-community-audience]] memory). `CardDropChecker._verify_session()` probes `/badges/` (checks `g_steamID = "<id>"`) and downgrades to unauthenticated (excluding unknowns + warning) when the session is logged out — preventing the bot from idling drained games on a store-only/expired token. `AUTO_BROWSER_COOKIES=true` (default) makes `main._recover_session_via_browser()` pull a valid community session from a locally logged-in browser via `steam/browser_cookies.py` (`browser_cookie3`, import-guarded; `BROWSER_COOKIES_BROWSER=auto|chrome|firefox|...`) — self-healing as the short-lived community token rotates.
- **Card counts**: when the badge API returns no `cards_remaining` (common once all badges are completed), `CardDropChecker._extract_drops_remaining()` parses the count from the badge page ("Jogo pode dar mais N cartas" / "N card drops remaining") into `drop_counts`; `main` feeds these into `IdleTracker` for the status panel and session report.

## Architecture

Entry: `__main__.py` → `main.main()` parses args, loads `Settings`, then either `launch_gui()` or constructs `SteamIdleBot`.

`SteamIdleBot` (`main.py`) is the orchestrator. On construction it wires together the backend client and the three Steam services, then `run()` drives a refresh loop.

### Idling backends (swappable)
Both expose the same client interface (`initialize/login/start_idling/stop_idling/is_connected/reconnect/refresh_games/sleep/logout/get_web_session`, plus `steam_id`/`username` properties). `build_steam_client()` selects by `IDLING_BACKEND`:
- `SteamClientWrapper` (`steam/client.py`) — default `python` backend using the `steam` library (`SteamClient`). Handles Steam Guard / 2FA prompts and builds authenticated web sessions.
- `SteamUtilityIdleClient` (`steam/steam_utility.py`) — delegates to an external `steam-utility-multiplataform` repo via `SteamUtilityBridge` (subprocess + JSON commands). Located via `STEAM_UTILITY_PATH` or sibling-directory autodiscovery.

Key resilience behavior: if the python backend fails to initialize, login, start, or reconnect, `SteamIdleBot._switch_to_steam_utility()` transparently falls back to the steam_utility backend (only when starting from `python`).

### Game selection pipeline
`GameManager.get_games_to_idle()` (`steam/games.py`) is the core filtering funnel, applied in order:
1. **Source** — owned games (Steam Web API if `STEAM_API_KEY`, else steam_utility) or the manual `GAME_APP_IDS`.
2. **Has trading cards** (`filter_trading_cards`) — prefers `BadgeService` badge catalog when an API key + steam_id are available; unknowns and fallback go through `TradingCardDetector` (store-page scraping, with a persistent JSON cache).
3. **Drops remaining** (`filter_completed_card_drops`) — `_filter_completed_card_drops()` prefers `BadgeService` (API badges), falling back to `CardDropChecker` (authenticated community-page scraping). Needs a steam_id; skipped otherwise. `CardDropChecker` keeps a persistent no-drop cache (`.cache/no_drop_cards.json`, keyed by steam_id, gated by `ENABLE_CARD_CACHE`): a game confirmed to have **no** remaining drops is recorded and skipped on later runs (a finished game never regains drops), so scraping only re-checks games that still had drops + new games. `_extract_drop_status` returns `(status, confident)`; only confident negatives (or authenticated-session negatives) are trusted permanently — weak/unauthenticated guesses are tagged and re-checked once an authenticated session is available. Positive verdicts are never cached (drop counts decrease while idling).
4. **Exclusions** (`EXCLUDE_APP_IDS`) then truncation to `max_games_to_idle` (Steam hard limit 32).

The three services are distinct: `TradingCardDetector` = *does this game have cards*; `BadgeService` = *badge/cards-remaining via API*; `CardDropChecker` = *drops remaining via scraping*. Authenticated web session from the client is pushed into the scrapers via `set_web_session()` / `set_session()`.

### Runtime loop & reporting
`_main_loop()` sleeps in 1s ticks (keeps GUI `stop()` responsive), re-runs the selection pipeline every 10 min, and reconnects on dropped connections (with steam_utility fallback). `IdleTracker` (`utils/idle_tracker.py`) snapshots cards-remaining before/after to compute drops, and writes a session report to `logs/idle_report_*.txt`. `DetailedLogger` (`utils/detailed_logger.py`) dumps per-stage JSON to `logs/`.

### GUI
`gui.py` (`SteamIdleBotGUI`) runs the bot on a worker thread, routes logs through a `QueueLogHandler`, handles Steam Guard code requests via dialogs, and persists settings with `save_to_env_file()`.

## Conventions

- Network/scraping code degrades gracefully: catch service-specific exceptions (`BadgeServiceError`, `CardDropCheckError`, `SteamUtilityError` in `utils/exceptions.py` and module-local classes) and fall back rather than abort.
- Backend methods are duck-typed across the two clients; new client features should be added to both backends (or guarded with `hasattr`/`getattr` as `main.py` already does for `get_web_session`).
- Tests mock Steam/network heavily; `*_extra.py` test files hold supplementary edge-case coverage alongside the base `test_<module>.py`.

## Dependency pins (don't break these)

`pyproject.toml` lists only direct deps as loose floors; `uv.lock` pins exact versions (run `uv lock --upgrade` to refresh). Two non-obvious constraints are load-bearing for the `steam` library:
- **`protobuf>=3.20,<4`** — the `steam[client]` extra ships protoc-generated `_pb2` modules that fail on protobuf 4+ (`Descriptors cannot be created directly`). Never bump to 4.x while on `steam` 1.4.x.
- **Do NOT add a standalone `eventemitter` package.** `steam.client` does `from eventemitter import EventEmitter`, but `steam[client]` already supplies this via `gevent-eventemitter` (a self-contained gevent-based `EventEmitter`). Installing the standalone `eventemitter` overwrites that module with an incompatible one and breaks the python backend at `SteamClient()` (`'SteamClient' object has no attribute '_listeners'`). An earlier `eventemitter==0.2.0` pin was removed for exactly this reason (commit `3f55645`); tests pass either way because they mock Steam, so a re-added pin only fails at runtime.
