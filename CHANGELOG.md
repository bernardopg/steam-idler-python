# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog, and this project adheres to Semantic Versioning.

## [Unreleased]

### Added

- GUI: **dark theme** — full Tokyo Night-inspired dark palette across all widgets (inputs, treeview, tabs, scrollbars, console, report, badges). Log lines color-coded by level (INFO/WARNING/ERROR/DEBUG/SUCCESS).
- GUI: **keyboard shortcuts** — `Ctrl+Enter` start, `Escape` stop, `Ctrl+L` clear logs, `Ctrl+S` save settings.
- GUI: **auto-scroll toggle** and **clear buttons** for both Live Logs and Session Report tabs.
- GUI: all CLI flags now have GUI equivalents — `Keep completed drops`, `Dry run`, `Stop App IDs` maintenance, `Log Level`, `Log File`.
- GUI: **171 tests** covering construction, settings loading/building, status badges, log/report operations, UI events, auth requests, status panel updates, start/stop lifecycle, collapsible sections, keyboard shortcuts, mousewheel scrolling, and the bot worker thread.

- CLI/config: **checkpoint report mode** — `--checkpoint-minutes N` (`CHECKPOINT_MINUTES`)
  writes a structured JSON + Markdown snapshot of the live session (selected games, card
  counts, drops, durations, totals) to `logs/checkpoints/` every N minutes; `--duration-minutes`
  (`DURATION_MINUTES`) stops idling after a fixed run length. New `IdleTracker.to_dict()`.
- CLI/config: **delayed post-run verification** — `--post-run-verify-seconds N`
  (`POST_RUN_VERIFY_SECONDS`) re-scrapes card counts N seconds after stopping, because Steam
  badge pages can lag behind the actual drops at the moment idling ends.
- CLI: **`--stop-app-ids`** maintenance mode — stop running steam-utility idles for the given
  App IDs (JSON or CSV) and exit, without starting the bot.
- Preflight: advisory **environment checks** for the `steam_utility` backend — warn when no
  local Steam client is running, and additionally when no graphical session
  (`DISPLAY`/`WAYLAND_DISPLAY`) is available to launch it. Never aborts; skipped for the
  `python` backend and on platforms without `/proc`.
- steam_utility: **idle process reconciliation** before starting — existing idles for target
  App IDs (e.g. from a previous run) are detected via `/proc`, the first is reused (adopted),
  duplicates are stopped, and idles for non-target apps are left untouched and reported. Avoids
  spawning duplicate idlers across restarts. Linux-only; a no-op without `/proc`.
- Drops: persistent **no-drop cache** (`.cache/no_drop_cards.json`, per account) — games
  confirmed without remaining drops are skipped on later runs, so each run scans less.
  New settings `DROP_CACHE_PATH` / `DROP_CACHE_TTL_DAYS`.
- Auth: **session verification** before trusting card-drop verdicts — a logged-out /
  store-only (`web:store`) session is detected and reported instead of silently idling
  drained games.
- Auth: **browser cookie recovery** — recover a valid `web:community` session from a
  locally logged-in browser. New settings `AUTO_BROWSER_COOKIES` / `BROWSER_COOKIES_BROWSER`
  (via the optional `browser-cookie3` dependency, import-guarded).
- UX: rich terminal **status panel** (game names, cards remaining, idle time) at start
  and on each refresh; resolved game names from the Steam API.
- UX: card-drop counts parsed from badge pages so the panel and session report show real
  numbers even when the badge API has no `cards_remaining`.
- CLI: `--config PATH` to load a custom configuration file.
- CLI/config: `--refresh-interval-seconds` flag and `REFRESH_INTERVAL_SECONDS` setting
  (default 600, min 10) to tune how often the selection pipeline re-runs while idling —
  previously hard-coded to 10 minutes.
- README: language toggle badges (English / Português-BR).

### Changed

- GUI: complete **UI overhaul** — dark theme replacing light palette, reorganized form with collapsible sections (no emoji prefixes), horizontal button row (Start | Stop | Save), themed Treeview status panel, and consistent dark treatment across all widgets.
- Drops: card-drop scraping only re-checks games that still had drops plus new games;
  per-game scrape/badge log spam moved to `DEBUG`, with concise summaries and scan progress.
- Docs (EN/PT-BR): rewritten for clarity — added Authentication & card-drop accuracy guide,
  idling backends, caches, GUI, and a full configuration reference; `.env` is now the
  documented primary config path. Security policy now covers cookie handling and the
  accepted protobuf advisories.

### Fixed

- **Main loop `UnboundLocalError`**: `new_games` was referenced outside its `if now - last_refresh` block, causing `cannot access local variable 'new_games'` errors every ~31 seconds until the first refresh interval triggered. Moved the game-comparison logic inside the refresh block.
- Idle tracker: `update_games()` now properly accumulates idle time when games are added/removed mid-session, and `end_session()` uses `stop_game()` for consistent timing.

- Card-drop filtering no longer idles fully-farmed games (or misses games with real drops)
  when the web session is not genuinely authenticated against `steamcommunity.com`.
- Terminal status panel now shows a **live, growing idle/session duration** instead of a
  frozen `0 min`: `IdleTracker` durations fall back to the current time while a session is
  still running (`end_time` not yet set).
- Logging: switched the file handler to a **rotating** one (10 MB × 3 backups) so a
  long-running idle session can no longer grow a single log file without bound.
- Trading-card detection tolerates malformed Steam `appdetails` payloads (e.g. app
  `2321720` returning a list where a dict is expected) instead of treating them as errors.
- Shutdown: `SIGINT`/`SIGTERM` now trigger a **graceful stop** that still emits the session
  report and runs cleanup. Previously `SIGTERM` (e.g. when `run.sh` is terminated) killed the
  process before the `finally` report could run.
- Report: final card counts are now **backfilled to 0** for games that started with known
  cards but are no longer reported by the authenticated badge/scraper read at stop — a drained
  badge means no remaining drops, so the session report shows a confident before/after instead
  of `?`. Backfill only runs when an authenticated read actually returned data.

### Security

- Account-name redaction is now consistent across both idling backends: the shared
  `utils.redaction.mask_username` helper masks the active account name in `steam_utility`
  connection logs (previously logged in full), matching the python backend.
- Documented why `protobuf` stays pinned `<4` (enforced by `steam[client]`), making
  advisories GHSA-8qvm-5x2c-j2w7 / GHSA-7gcm-g887-7qv7 non-actionable; accepted as
  tolerable risk (only trusted Steam-server data is deserialized).
