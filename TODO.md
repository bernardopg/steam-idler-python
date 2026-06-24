# TODO

The full, prioritized backlog — epics, user stories, impact/effort, sprints and known
risks — now lives in **[BACKLOG.md](BACKLOG.md)**.

Delivered work is recorded in [`CHANGELOG.md`](CHANGELOG.md).

## Completed: GUI/Terminal Parity

- [x] Make the Tkinter GUI expose every runtime setting available to the terminal path.
- [x] Keep `./run.sh` as the operational baseline: UV environment, run transcript under `logs/runs/`, graceful stop, and session reports.
- [x] Add GUI support for backend selection, steam-utility path, browser cookie recovery, no-drop cache, refresh interval, checkpoints, duration limit, post-run verification, and stop-specific-App-ID maintenance.
- [x] Add automated parity tests so future `Settings` or CLI additions cannot silently miss the GUI.
