"""Best-effort environment preflight checks emitted before idling starts.

These are advisory only: they never abort the run. They exist because the
``steam_utility`` backend drives a *locally running* Steam client and, when Steam
is closed, needs a graphical session to launch it. The default ``python`` backend
connects to Steam's network directly and does not care, so the Steam-process
warning is scoped to the ``steam_utility`` backend to avoid false positives.
"""

from __future__ import annotations

__all__ = ["has_graphical_session", "is_steam_running", "preflight_warnings"]

import os
from collections.abc import Mapping
from pathlib import Path

_GRAPHICAL_ENV_VARS = ("DISPLAY", "WAYLAND_DISPLAY")


def has_graphical_session(env: Mapping[str, str] | None = None) -> bool:
    """Return True when a graphical session variable is set (X11 or Wayland)."""
    env = os.environ if env is None else env
    return any(env.get(var) for var in _GRAPHICAL_ENV_VARS)


def is_steam_running(proc_root: str = "/proc") -> bool | None:
    """Detect a running Steam client by scanning ``/proc``.

    Returns ``True``/``False`` on Linux, or ``None`` when detection is not
    possible (no ``/proc``, e.g. non-Linux platforms) so callers can stay quiet
    instead of emitting a misleading warning.
    """
    root = Path(proc_root)
    if not root.is_dir():
        return None

    found_any = False
    for entry in root.iterdir():
        if not entry.name.isdigit():
            continue
        comm = entry / "comm"
        try:
            name = comm.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            continue
        found_any = True
        # Steam's main process reports as "steam"; helper processes use names
        # like "steamwebhelper" — match the primary client only.
        if name == "steam":
            return True

    # If we could read at least one comm entry, absence is a real negative.
    return False if found_any else None


def preflight_warnings(
    backend: str,
    *,
    env: Mapping[str, str] | None = None,
    proc_root: str = "/proc",
) -> list[str]:
    """Build advisory warning messages for the given idling backend.

    Only the ``steam_utility`` backend depends on a local Steam client, so the
    checks are skipped entirely for other backends.
    """
    if backend != "steam_utility":
        return []

    warnings: list[str] = []
    running = is_steam_running(proc_root)
    if running is False:
        warnings.append(
            "Steam does not appear to be running; the steam_utility backend needs "
            "a logged-in Steam client to idle games."
        )
        if not has_graphical_session(env):
            warnings.append(
                "No graphical session detected (DISPLAY/WAYLAND_DISPLAY unset); "
                "Steam cannot be launched automatically from this shell."
            )
    return warnings
