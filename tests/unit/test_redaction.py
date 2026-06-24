"""Tests for the shared log-redaction helper."""

from __future__ import annotations

import pytest

from steam_idle_bot.steam.client import _mask_username
from steam_idle_bot.utils.redaction import mask_username


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, "***"),
        ("", "***"),
        ("abc", "***"),
        ("ab", "***"),
        ("steambot", "ste***t"),
        ("bernardo", "ber***o"),
    ],
)
def test_mask_username(value, expected):
    assert mask_username(value) == expected


def test_client_alias_points_to_shared_helper():
    # The client backend reuses the canonical helper for consistent masking.
    assert _mask_username is mask_username
    assert _mask_username("steambot") == "ste***t"
