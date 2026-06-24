# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog, and this project adheres to Semantic Versioning.

## [Unreleased]

### Added

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

- Drops: card-drop scraping only re-checks games that still had drops plus new games;
  per-game scrape/badge log spam moved to `DEBUG`, with concise summaries and scan progress.
- Docs (EN/PT-BR): rewritten for clarity — added Authentication & card-drop accuracy guide,
  idling backends, caches, GUI, and a full configuration reference; `.env` is now the
  documented primary config path. Security policy now covers cookie handling and the
  accepted protobuf advisories.

### Fixed

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

### Security

- Account-name redaction is now consistent across both idling backends: the shared
  `utils.redaction.mask_username` helper masks the active account name in `steam_utility`
  connection logs (previously logged in full), matching the python backend.
- Documented why `protobuf` stays pinned `<4` (enforced by `steam[client]`), making
  advisories GHSA-8qvm-5x2c-j2w7 / GHSA-7gcm-g887-7qv7 non-actionable; accepted as
  tolerable risk (only trusted Steam-server data is deserialized).
