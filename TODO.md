# TODO

## Card-Drop Accuracy

- Add a structured checkpoint report mode, for example
  `--checkpoint-minutes 5 --duration-minutes 25`, writing JSON/Markdown with
  selected games, card counts, drops, refreshes, and cleanup status.
- Add delayed post-run verification, e.g. scrape immediately at stop and again
  after 30-60 seconds, because Steam badge pages can lag behind actual drops.
- Investigate why Badge API returns no card-drop data for all candidates and
  document whether that is expected for this account/API endpoint.

## Operational Hygiene

- Add a command or CLI flag to stop only bot-owned steam-utility idles by App ID.
- Add integration tests around `run.sh` signal handling and orphan subprocess
  prevention.
