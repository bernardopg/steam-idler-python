"""Tests for TradingCardDetector cache persistence and TTL expiry."""

import json
import time
from pathlib import Path

from steam_idle_bot.steam.trading_cards import TradingCardDetector


def test_cache_persistence_and_reload(tmp_path: Path, monkeypatch):
    cache_file = tmp_path / "cards.json"
    det = TradingCardDetector(
        cache_enabled=True, cache_path=str(cache_file), cache_ttl_days=30
    )

    # Remember a couple of entries and persist
    det._remember(42, True)
    det._remember(99, False)
    det._save_cache()

    assert cache_file.exists()
    raw = json.loads(cache_file.read_text())
    assert "42" in raw and raw["42"]["has_cards"] is True
    assert "99" in raw and raw["99"]["has_cards"] is False

    # New detector should load the persisted cache
    det2 = TradingCardDetector(
        cache_enabled=True, cache_path=str(cache_file), cache_ttl_days=30
    )
    assert det2._cache.get(42) is True
    assert det2._cache.get(99) is False


def test_cache_ttl_expiry(tmp_path: Path, monkeypatch):
    cache_file = tmp_path / "cards.json"
    det = TradingCardDetector(
        cache_enabled=True, cache_path=str(cache_file), cache_ttl_days=1
    )

    # Insert an entry with an old timestamp (2 days ago)
    past_ts = time.time() - 2 * 86400
    det._cache_data[7] = (True, past_ts)
    det._save_cache()

    # Load with TTL of 1 day → entry should be ignored
    det2 = TradingCardDetector(
        cache_enabled=True, cache_path=str(cache_file), cache_ttl_days=1
    )
    assert 7 not in det2._cache
