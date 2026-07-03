# TODO

The full, prioritized backlog — epics, user stories, impact/effort, sprints and known
risks — now lives in **[BACKLOG.md](BACKLOG.md)**.

Delivered work is recorded in [`CHANGELOG.md`](CHANGELOG.md).

## Last audit: 2026-07-03 (Sprint 6)

Shipped: terminal color fix under `run.sh` (FIFO ≠ TTY made rich drop ANSI), reconnect
exponential backoff, live status-panel reprint every refresh, CI gates (ruff check +
format + mypy + `--cov-fail-under=85` + pytest-timeout), PyPI packaging groundwork
(hatchling + `steam-idle-bot` entry point), bounded `DetailedLogger` outputs.

Next up (see BACKLOG §📌): finish **F1** (PyPI release workflow), **C3** (backend
conformance tests), **H2** (logger redaction), **I2** (troubleshooting matrix), **D4**
(default log path under `logs/`).

## Completed: GUI/Terminal Parity

- [x] Make the Tkinter GUI expose every runtime setting available to the terminal path.
- [x] Keep `./run.sh` as the operational baseline: UV environment, run transcript under `logs/runs/`, graceful stop, and session reports.
- [x] Add GUI support for backend selection, steam-utility path, browser cookie recovery, no-drop cache, refresh interval, checkpoints, duration limit, post-run verification, and stop-specific-App-ID maintenance.
- [x] Add automated parity tests so future `Settings` or CLI additions cannot silently miss the GUI.
