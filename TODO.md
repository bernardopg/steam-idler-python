# TODO

## High Priority

- Add a first-class `--refresh-interval-seconds` CLI flag and matching setting so
  real idle verification can run at 5-minute intervals without external scripts.
- Fix terminal idle duration display; the panel currently reports `0 min` after
  10+ minutes of real idling.
- Make shutdown produce a final report reliably when stopping from `run.sh` with
  Ctrl+C, not only cleanup subprocesses.
- Add steam-utility process reconciliation: detect existing idles for target App
  IDs before starting, deduplicate them, and report whether they are reused,
  stopped, or left untouched.

## Card-Drop Accuracy

- Harden Steam Store `appdetails` parsing for unexpected payloads such as app
  `2321720`, where the current parser can receive a list instead of a dict.
- Add a structured checkpoint report mode, for example
  `--checkpoint-minutes 5 --duration-minutes 25`, writing JSON/Markdown with
  selected games, card counts, drops, refreshes, and cleanup status.
- Add delayed post-run verification, e.g. scrape immediately at stop and again
  after 30-60 seconds, because Steam badge pages can lag behind actual drops.
- Improve final card-count capture so the session report always includes before
  and after card counts from the authenticated scraper.
- Investigate why Badge API returns no card-drop data for all candidates and
  document whether that is expected for this account/API endpoint.

## Operational Hygiene

- Add a command or CLI flag to stop only bot-owned steam-utility idles by App ID.
- Add a preflight warning when Steam is not running or when the shell lacks the
  graphical session variables needed to start Steam.
- Redact account names consistently in runtime logs, including steam-utility
  connection messages.
- Add integration tests around `run.sh` signal handling and orphan subprocess
  prevention.
