"""Integration tests for OS-signal-driven graceful shutdown and run.sh wiring."""

from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from pathlib import Path

from steam_idle_bot.config.settings import Settings
from steam_idle_bot.main import SteamIdleBot, _install_signal_handlers

REPO_ROOT = Path(__file__).resolve().parents[2]


class _DummyClient:
    steam_id = "1"

    def sleep(self, seconds):
        time.sleep(0.01)

    def is_connected(self):
        return True

    def stop_idling(self):
        return True


def _settings():
    return Settings(
        username="user",
        password="pass",
        refresh_interval_seconds=600,
        filter_completed_card_drops=False,
    )


def test_sigterm_triggers_graceful_loop_exit():
    """A real SIGTERM must unwind _main_loop via the installed handler."""
    orig_int = signal.getsignal(signal.SIGINT)
    orig_term = signal.getsignal(signal.SIGTERM)
    try:
        bot = SteamIdleBot(_settings(), console_output=False)
        bot.client = _DummyClient()
        _install_signal_handlers(bot)
        bot._stop_event.clear()

        worker = threading.Thread(target=bot._main_loop, args=([10],), kwargs={"steam_id": "1"})
        worker.start()
        time.sleep(0.2)

        os.kill(os.getpid(), signal.SIGTERM)
        worker.join(timeout=5)

        assert not worker.is_alive()
        assert bot._stop_event.is_set()
    finally:
        signal.signal(signal.SIGINT, orig_int)
        signal.signal(signal.SIGTERM, orig_term)


def test_run_sh_is_valid_and_forwards_signals():
    """run.sh must parse and keep the FIFO/tee + trap wiring that lets Ctrl+C reach the bot."""
    run_sh = REPO_ROOT / "run.sh"
    assert run_sh.is_file()

    # Bash syntax check — fails the test on a malformed script.
    result = subprocess.run(["bash", "-n", str(run_sh)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr

    text = run_sh.read_text(encoding="utf-8")
    assert "trap " in text
    assert "mkfifo" in text
    # Python must not be the head of a pipeline, so Ctrl+C reaches it directly.
    assert "> \"$FIFO\"" in text
