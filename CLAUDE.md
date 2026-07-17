# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Steam Idle Bot — automates Steam playtime farming and trading-card drops. Python package `steam_idle_bot` under a `src/` layout, managed with `uv`. Runs as a terminal workflow or via the web UI (FastAPI + React).

## Commands

All commands run through `uv` (it auto-syncs the environment).

```bash
# Run the bot (terminal). Wraps `uv sync` + `python -m steam_idle_bot`, tees output to logs/runs/
./run.sh
./run.sh --dry-run              # print config + chosen games, no Steam contact
./run.sh --no-trading-cards     # skip trading-card filtering
./run.sh --max-games 10         # cap idled games
./run.sh --refresh-interval-seconds 300  # re-run the selection pipeline every 5 min
STEAM_IDLE_SKIP_SYNC=1 ./run.sh --dry-run  # skip runner uv sync for quick local smoke tests
STEAM_IDLE_RUNNER_VERBOSE=1 ./run.sh       # show uv sync output during runner preflight
./run-web.sh                    # launch the web UI (== python -m steam_idle_bot --web); builds frontend/ on demand
# Frontend dev loop (Vite dev server proxying /api to a running --web backend):
#   cd frontend && npm install && npm run dev

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
- `save_to_env_file()` serializes settings back to `.env` — used by the web UI to persist user changes.
- CLI flags in `main.py` override loaded settings (`--max-games`, `--refresh-interval-seconds`, `--checkpoint-minutes`, `--duration-minutes`, `--post-run-verify-seconds`, `--no-cache`, `--max-checks`, `--skip-failures`, `--keep-completed-drops`, `--no-trading-cards`). `--stop-app-ids "570,730"` is a maintenance mode that stops running steam-utility idles for those App IDs and exits without starting the bot.
- **Web session auth**: card-drop scraping needs a `web:community` `steamLoginSecure` (see [[steam-web-cookies-community-audience]] memory). `CardDropChecker._verify_session()` probes `/badges/` (checks `g_steamID = "<id>"`) and downgrades to unauthenticated (excluding unknowns + warning) when the session is logged out — preventing the bot from idling drained games on a store-only/expired token. `AUTO_BROWSER_COOKIES=true` (default) makes `main._recover_session_via_browser()` pull a valid community session from a locally logged-in browser via `steam/browser_cookies.py` (`browser_cookie3`, import-guarded; `BROWSER_COOKIES_BROWSER=auto|chrome|firefox|...`) — self-healing as the short-lived community token rotates.
- **Card counts**: when the badge API returns no `cards_remaining` (common once all badges are completed), `CardDropChecker._extract_drops_remaining()` parses the count from the badge page ("Jogo pode dar mais N cartas" / "N card drops remaining") into `drop_counts`; `main` feeds these into `IdleTracker` for the status panel and session report.
- **Badge API returning no card-drop data (expected)**: the Steam `IPlayerService/GetBadges` endpoint only carries `cards_remaining` for badges that are *in progress*. Accounts whose candidate games already completed their badges (or whose drops reset on a weekly timer not yet started) legitimately get an empty/absent `cards_remaining` for every candidate — this is normal, not a bug or auth failure. The bot is designed around it: it falls back to authenticated badge-page scraping (`CardDropChecker` / `_extract_drops_remaining`) for the real per-game counts, and `_backfill_drained_final_counts()` records `0` for games the authenticated read no longer lists. So an all-empty Badge API response is expected; only an empty *scraper* response on a logged-out session (see Web session auth above) indicates a real problem.

## Architecture

Entry: `__main__.py` → `main.main()` parses args, loads `Settings`, then either `launch_web()` (also reached via the deprecated `--gui` flag) or constructs `SteamIdleBot`.

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
3. **Drops remaining** (`filter_completed_card_drops`) — `_filter_completed_card_drops()` prefers `BadgeService` (API badges), falling back to `CardDropChecker` (authenticated community-page scraping). Needs a steam_id; skipped otherwise. `BadgeService` keeps a short in-memory badge payload cache for filtering calls; `get_cards_remaining()` bypasses it for authoritative before/after snapshots. `CardDropChecker` keeps a persistent no-drop cache (`.cache/no_drop_cards.json`, keyed by steam_id, gated by `ENABLE_CARD_CACHE`): a game confirmed to have **no** remaining drops is recorded and skipped on later runs (a finished game never regains drops), so scraping only re-checks games that still had drops + new games. `_extract_drop_status` returns `(status, confident)`; only confident negatives (or authenticated-session negatives) are trusted permanently — weak/unauthenticated guesses are tagged and re-checked once an authenticated session is available. Positive verdicts are cached only briefly in memory (`_has_drops_cache`, 5 min) to avoid re-scraping the same active games on every refresh; they are never persisted because drop counts decrease while idling.
4. **Exclusions** (`EXCLUDE_APP_IDS` + session-only drained exclusions) then truncation to `max_games_to_idle` (Steam hard limit 32). `SteamIdleBot` can pass transient `session_exclude_app_ids` when inventory snapshots prove a game dropped all known remaining cards before Steam badge pages update, allowing refreshes to rotate in the next candidate.

The three services are distinct: `TradingCardDetector` = *does this game have cards*; `BadgeService` = *badge/cards-remaining via API*; `CardDropChecker` = *drops remaining via scraping*. Authenticated web session from the client is pushed into the scrapers via `set_web_session()` / `set_session()`.

### Runtime loop & reporting
`_main_loop()` sleeps in 1s ticks (keeps controller `stop()` responsive), re-runs the selection pipeline every `refresh_interval_seconds` (default 10 min), and reconnects on dropped connections (with steam_utility fallback). Refresh calls use `GameManager.get_games_to_idle(..., quiet=True)` so repeated unchanged scans log progress at DEBUG while warnings/errors stay visible. During refresh, `_capture_inventory_progress()` compares the current trading-card inventory to the pre-run snapshot; if `inventory_drops >= cards_before` for an idled game, the app ID is added to `_session_drained_app_ids` and excluded from the next selection. `IdleTracker` (`utils/idle_tracker.py`) snapshots cards-remaining before/after and inventory drops to compute drops, and writes a session report to `logs/idle_report_*.txt`. `DetailedLogger` (`utils/detailed_logger.py`) dumps per-stage JSON to `logs/`.

`IdleTracker` reports the source of each drop count: `remaining-count` (before/after card count decreased), `inventory` (inventory confirmed cards while badge/scraper count lagged), or `count+inventory` (both sources agree). This avoids misleading report lines like `Cards: 3 → 3 (+1)` without explaining that inventory was the authoritative source.

`run.sh` is part of the terminal UX contract: it prints a compact banner, writes bot output to `logs/runs/run_*.log`, uses a FIFO/tee setup so Python is not the head of a shell pipeline and Ctrl+C reaches the bot directly, clears stale exported bot env vars by default so `.env` wins, and supports `STEAM_IDLE_PRESERVE_ENV=1`, `STEAM_IDLE_SKIP_SYNC=1`, and `STEAM_IDLE_RUNNER_VERBOSE=1`.

### Web UI
`webapi/` is the recommended graphical frontend: `controller.py` (`BotController`) owns the bot
worker thread (`report_callback`, `auth_code_provider` blocking on an
Event, per-run transcript under `logs/runs/`) plus a sequenced event ring buffer; `server.py`
(`create_app`/`launch_web`) exposes REST (`/api/status|settings|bot/start|bot/stop|auth-code|
stop-app-ids|report`) + WebSocket `/api/ws` (init payload, then log/status/report/auth events and
periodic snapshots), and serves the built React app from `frontend/dist`. The frontend
(React 19 + Vite + TypeScript + Tailwind 4, dark emerald theme) lives in `frontend/`;
`test_webapi.py` enforces parity between the React settings form and `Settings` fields.
Settings PUT masks/reuses the saved password and tolerates CSV list fields.

## Conventions

- Network/scraping code degrades gracefully: catch service-specific exceptions (`BadgeServiceError`, `CardDropCheckError`, `SteamUtilityError` in `utils/exceptions.py` and module-local classes) and fall back rather than abort.
- Backend methods are duck-typed across the two clients; new client features should be added to both backends (or guarded with `hasattr`/`getattr` as `main.py` already does for `get_web_session`).
- Tests mock Steam/network heavily; `*_extra.py` test files hold supplementary edge-case coverage alongside the base `test_<module>.py`.

## Dependency pins (don't break these)

`pyproject.toml` lists only direct deps as loose floors; `uv.lock` pins exact versions (run `uv lock --upgrade` to refresh). Two non-obvious constraints are load-bearing for the `steam` library:
- **`protobuf>=3.20,<4`** — the `steam[client]` extra ships protoc-generated `_pb2` modules that fail on protobuf 4+ (`Descriptors cannot be created directly`). Never bump to 4.x while on `steam` 1.4.x.
- **Do NOT add a standalone `eventemitter` package.** `steam.client` does `from eventemitter import EventEmitter`, but `steam[client]` already supplies this via `gevent-eventemitter` (a self-contained gevent-based `EventEmitter`). Installing the standalone `eventemitter` overwrites that module with an incompatible one and breaks the python backend at `SteamClient()` (`'SteamClient' object has no attribute '_listeners'`). An earlier `eventemitter==0.2.0` pin was removed for exactly this reason (commit `3f55645`); tests pass either way because they mock Steam, so a re-added pin only fails at runtime.
