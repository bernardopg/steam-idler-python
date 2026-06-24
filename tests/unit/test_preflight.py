"""Tests for advisory environment preflight checks."""

from __future__ import annotations

from steam_idle_bot.utils.preflight import (
    has_graphical_session,
    is_steam_running,
    preflight_warnings,
)


def _make_proc(tmp_path, processes):
    """Build a fake /proc tree: processes maps pid -> comm name."""
    for pid, comm in processes.items():
        d = tmp_path / str(pid)
        d.mkdir()
        (d / "comm").write_text(f"{comm}\n", encoding="utf-8")
    # A non-numeric entry should be ignored by the scanner.
    (tmp_path / "self").mkdir()
    return str(tmp_path)


def test_has_graphical_session():
    assert has_graphical_session({"DISPLAY": ":0"}) is True
    assert has_graphical_session({"WAYLAND_DISPLAY": "wayland-0"}) is True
    assert has_graphical_session({}) is False
    assert has_graphical_session({"DISPLAY": ""}) is False


def test_is_steam_running_detects_steam(tmp_path):
    proc = _make_proc(tmp_path, {10: "steam", 11: "steamwebhelper"})
    assert is_steam_running(proc) is True


def test_is_steam_running_negative(tmp_path):
    proc = _make_proc(tmp_path, {10: "bash", 11: "steamwebhelper"})
    assert is_steam_running(proc) is False


def test_is_steam_running_unknown_without_proc(tmp_path):
    assert is_steam_running(str(tmp_path / "missing")) is None


def test_preflight_skips_non_steam_utility_backend(tmp_path):
    proc = _make_proc(tmp_path, {10: "bash"})
    assert preflight_warnings("python", env={}, proc_root=proc) == []


def test_preflight_warns_when_steam_down_and_headless(tmp_path):
    proc = _make_proc(tmp_path, {10: "bash"})
    warnings = preflight_warnings("steam_utility", env={}, proc_root=proc)
    assert len(warnings) == 2
    assert "Steam does not appear to be running" in warnings[0]
    assert "No graphical session" in warnings[1]


def test_preflight_warns_steam_down_with_graphical_session(tmp_path):
    proc = _make_proc(tmp_path, {10: "bash"})
    warnings = preflight_warnings("steam_utility", env={"DISPLAY": ":0"}, proc_root=proc)
    assert len(warnings) == 1
    assert "Steam does not appear to be running" in warnings[0]


def test_preflight_silent_when_steam_running(tmp_path):
    proc = _make_proc(tmp_path, {10: "steam"})
    assert preflight_warnings("steam_utility", env={}, proc_root=proc) == []


def test_preflight_silent_when_detection_unknown(tmp_path):
    # No /proc available (e.g. non-Linux): stay quiet rather than warn falsely.
    missing = str(tmp_path / "missing")
    assert preflight_warnings("steam_utility", env={}, proc_root=missing) == []
