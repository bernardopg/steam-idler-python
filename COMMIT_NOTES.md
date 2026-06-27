# Commit notes: optimize refresh filtering, reports, and shell UX

## Suggested commit message

```text
perf: optimize refresh filtering and shell UX

Cache Steam badge payloads and short-lived positive drop verdicts during a
session, reduce repeated refresh log noise, and rotate out games whose known
remaining drops were confirmed by inventory before badge pages catch up. Improve
the terminal runner and clarify inventory-vs-badge drop sources in reports.
```

## Executive summary

This change addresses two problems observed from the latest `logs/runs/` output:

1. The bot repeatedly re-ran the same expensive selection pipeline every refresh interval even when candidate inputs did not change.
2. The final report could look inconsistent when Steam badge/scraper counts lagged behind inventory: e.g. `Cards: 2 → 2` while inventory confirmed a drop.

The updated behavior keeps correctness conservative while improving runtime efficiency and shell UX:

1. `BadgeService` caches full badge API payloads briefly in memory for filtering calls.
2. `CardDropChecker` caches positive "has drops" verdicts briefly in memory so active games are not re-scraped every refresh.
3. Refresh-time progress logs are demoted to DEBUG via `GameManager.get_games_to_idle(..., quiet=True)`.
4. Inventory snapshots update mid-session: when inventory-confirmed drops equal all known remaining cards for an idled game, that game is excluded from the next refresh so another candidate can take its slot even if badge pages lag.
5. `IdleTracker` reports the source of each drop total (`remaining-count`, `inventory`, or `count+inventory`) and explicitly explains badge-count lag.
6. `./run.sh` now has a clearer terminal UX while preserving signal correctness.

## User-visible impact

- Refresh cycles produce far less repeated INFO noise when the selected games do not change.
- Sessions with short refresh intervals avoid redundant badge-page scraping for games just confirmed to still have drops.
- Long sessions can rotate out games that have already dropped all known remaining cards according to inventory.
- Reports no longer look contradictory when `Cards: before → after` did not decrease but inventory confirmed drops.
- Terminal runs are easier to read: banner, log path, quiet preflight sync, clear Ctrl+C instruction, and success/failure footer.
- The first startup scan remains fully informative at INFO level; warnings and errors are never hidden.

## Root cause

The run logs showed the same candidate set being recomputed repeatedly. Each refresh re-fetched badge data and re-scraped badge pages even though no inputs had changed. Steam badge pages can also lag behind inventory, so a game can be effectively drained while the badge page still reports stale remaining-count text. The drop totals were correct because inventory is authoritative for newly acquired cards, but the report did not identify that source clearly.

## Technical changes

### `src/steam_idle_bot/steam/badges.py`

- Added a short in-memory `_badges_cache` keyed by Steam ID.
- Filtering paths reuse cached badge payloads within the TTL.
- `get_cards_remaining()` bypasses the cache via `use_cache=False` so before/after snapshots remain fresh.
- `clear_cache()` now clears the badge cache.

### `src/steam_idle_bot/steam/card_drops.py`

- Added `_has_drops_cache`, a short-lived positive verdict cache keyed by normalized Steam ID and app ID.
- Positive verdicts are cached only in memory and only briefly; they are not persisted because drop counts decrease while idling.
- Persistent no-drop cache behavior remains unchanged.

### `src/steam_idle_bot/steam/games.py`

- Added `quiet=True` mode to demote repeated refresh progress logs from INFO to DEBUG.
- Added `session_exclude_app_ids` so the orchestrator can exclude games drained during the current session without mutating persistent settings.

### `src/steam_idle_bot/main.py`

- Refresh calls now use `quiet=True` and pass session-only drained exclusions.
- Added `_capture_inventory_progress()` for mid-session inventory checks.
- If inventory-confirmed drops meet or exceed `cards_before`, the app ID is added to `_session_drained_app_ids` for refresh-time rotation.
- Final inventory capture reuses the same progress helper with final reporting enabled.

### `src/steam_idle_bot/utils/idle_tracker.py`

- Added `remaining_count_drops`, `drop_source`, and `count_lagged_inventory` helpers.
- Report summary tables now include a drop source column.
- Detailed breakdown explicitly explains when inventory is used because badge/scraper counts lagged.
- Structured snapshots now include `drop_source` and `count_lagged_inventory`.

### `run.sh`

- Added a compact startup banner and exit footer with elapsed time and log path.
- Preserved the FIFO/tee design so Python is not the head of a pipeline and Ctrl+C reaches the bot.
- Replaced race-prone `mktemp -u` FIFO creation with a private `mktemp -d` directory.
- Made `uv sync` quiet by default, with `STEAM_IDLE_RUNNER_VERBOSE=1` to show output and `STEAM_IDLE_SKIP_SYNC=1` for quick local smoke tests.
- Kept `.env` precedence behavior and documented `STEAM_IDLE_PRESERVE_ENV=1`.

### Tests

- Added `tests/unit/test_efficiency_caches.py` for badge caching, positive drop caching, and quiet logging behavior.
- Added coverage for session-only excludes and inventory-driven rotation.
- Added/updated coverage for report drop sources and `run.sh` runner invariants.
- Updated test doubles to match the expanded `get_games_to_idle(..., quiet=False, session_exclude_app_ids=None)` contract.

### Documentation

- Updated `README.md` test badge, feature table, and runner notes.
- Updated English and Portuguese README architecture/usage/report sections.
- Updated English, Portuguese, and compatibility Usage guides.
- Updated `CLAUDE.md` architecture/runner notes for future coding agents.

## Validation performed

Run after implementation and documentation edits:

```bash
uv run pytest -q tests/unit/
```

Result:

```text
560 passed in 69.75s (0:01:09)
FINAL_EXIT:0
```

Focused checks already run for the runner/report changes:

```bash
bash -n run.sh
shellcheck run.sh
uv run pytest -q tests/unit/test_signal_integration.py tests/unit/test_idle_tracker.py
uv run ruff check src/steam_idle_bot/utils/idle_tracker.py tests/unit/test_idle_tracker.py tests/unit/test_signal_integration.py
STEAM_IDLE_SKIP_SYNC=1 STEAM_IDLE_PRESERVE_ENV=1 USERNAME=test_user PASSWORD=*** GAME_APP_IDS=10 FILTER_TRADING_CARDS=false USE_OWNED_GAMES=false ./run.sh --dry-run --no-trading-cards --max-games 1
```

Results:

```text
bash -n: passed
shellcheck: passed
targeted pytest: 14 passed
ruff: All checks passed
run.sh smoke: passed, exit 0
```

Static checks expected before commit:

```bash
uv run ruff check src/steam_idle_bot/ tests/unit/test_efficiency_caches.py tests/unit/test_games.py tests/unit/test_idle_tracker.py tests/unit/test_main_cli.py tests/unit/test_main_extra.py tests/unit/test_signal_integration.py tests/unit/test_steam_idle_bot.py
uv run mypy src
```

## Security and privacy notes

- No credentials, cookies, API keys, passwords, or token values are included in this note.
- The change does not read or commit `.env`.
- Inventory handling continues to use the existing authenticated web session and records only card metadata already used for reporting.
- Staged files should be controlled explicitly; do not use broad `git add -A` in this repo.

## Staging plan

```bash
git add \
  src/steam_idle_bot/main.py \
  src/steam_idle_bot/steam/badges.py \
  src/steam_idle_bot/steam/card_drops.py \
  src/steam_idle_bot/steam/games.py \
  src/steam_idle_bot/utils/idle_tracker.py \
  run.sh \
  tests/unit/test_efficiency_caches.py \
  tests/unit/test_games.py \
  tests/unit/test_idle_tracker.py \
  tests/unit/test_main_cli.py \
  tests/unit/test_main_extra.py \
  tests/unit/test_signal_integration.py \
  tests/unit/test_steam_idle_bot.py \
  README.md \
  docs/en/README.md \
  docs/en/USAGE.md \
  docs/pt-br/README.md \
  docs/pt-br/USAGE.md \
  docs/USAGE.md \
  CLAUDE.md \
  COMMIT_NOTES.md
```

## Push plan

```bash
git commit -m "perf: optimize refresh filtering and shell UX"
git push origin main
```
