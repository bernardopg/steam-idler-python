"""Helpers for redacting sensitive values (account names, credentials) in logs."""

from __future__ import annotations

__all__ = ["mask_username"]


def mask_username(username: str | None) -> str:
    """Mask a username for safe logging (e.g. ``'ste***bot'``).

    Short or empty names collapse to ``'***'`` so no identifying prefix leaks.
    """
    if not username or len(username) <= 3:
        return "***"
    return f"{username[:3]}***{username[-1]}"
