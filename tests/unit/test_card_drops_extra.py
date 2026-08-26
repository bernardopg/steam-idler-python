"""Additional tests for CardDropChecker parsing and fallbacks."""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
import requests

from steam_idle_bot.config.settings import Settings
from steam_idle_bot.steam.card_drops import CardDropChecker, CardDropCheckError
from steam_idle_bot.utils.exceptions import SteamAPITimeoutError


def make_settings() -> Settings:
    return Settings(username="user", password="pass")


class Resp:
    def __init__(self, text: str):
        self.text = text

    def raise_for_status(self):
        return None


class Sess:
    def __init__(self, text="", exc=None):
        self.text = text
        self.exc = exc

    def get(self, *args, **kwargs):
        if self.exc:
            raise self.exc
        return Resp(self.text)


def make_checker(text="", exc=None):
    with patch(
        "steam_idle_bot.steam.card_drops.CardDropChecker._build_session",
        return_value=Sess(text, exc),
    ):
        checker = CardDropChecker(make_settings())
    checker.detailed_logger.log_scraping_result = Mock()
    checker.detailed_logger.log_api_results = Mock()
    return checker


@pytest.mark.parametrize(
    "steam_id,expected",
    [
        (
            "profiles/76561198000000000",
            "https://steamcommunity.com/profiles/76561198000000000/gamecards/10/",
        ),
        ("id/myname", "https://steamcommunity.com/id/myname/gamecards/10/"),
        (
            "https://steamcommunity.com/id/custom/",
            "https://steamcommunity.com/id/custom/gamecards/10/",
        ),
    ],
)
def test_build_gamecards_url_variants(steam_id, expected):
    assert CardDropChecker._build_gamecards_url(steam_id, 10) == expected


def test_build_gamecards_url_empty_errors():
    with pytest.raises(ValueError):
        CardDropChecker._build_gamecards_url("   ", 10)
    assert CardDropChecker._build_gamecards_url("profiles/", 10).endswith("/id/profiles/gamecards/10/")


@pytest.mark.parametrize(
    "html,expected",
    [
        ("não dará mais cartas", False),
        ("pode dar mais cartas", True),
        ("no card drops remaining", False),
        ("can drop more", True),
        ('<span class="progress_info_bold">não dará mais</span>', False),
        ('<span class="progress_info_bold">drops remaining</span>', True),
        ('<span class="progress_info_bold">3/5</span>', True),
        ('<span class="progress_info_bold">2</span>', False),
        ('<span class="progress_info_bold">unknown words</span>', False),
        ('<div class="badge_title_stats_drops"></div>', False),
        ("sign in to see more", False),
        ("trading cards available", False),
        ("completely unknown page", False),
        ("0 card drops remaining", False),
        ("2 card drops remaining", True),
    ],
)
def test_has_remaining_drops_patterns(html, expected):
    checker = make_checker(text=html)
    assert checker.has_remaining_drops(10, "123") is expected


def test_has_remaining_drops_timeout_and_network_errors():
    checker_timeout = make_checker(exc=requests.exceptions.Timeout())
    with pytest.raises(SteamAPITimeoutError):
        checker_timeout.has_remaining_drops(10, "123")

    checker_network = make_checker(exc=requests.exceptions.RequestException("boom"))
    with pytest.raises(CardDropCheckError):
        checker_network.has_remaining_drops(10, "123")


def test_has_remaining_drops_unexpected_error_wrapped(monkeypatch):
    checker = make_checker(text="pode dar mais")
    monkeypatch.setattr(
        checker,
        "_build_gamecards_url",
        lambda steam_id, app_id: (_ for _ in ()).throw(RuntimeError("bad")),
    )

    with pytest.raises(CardDropCheckError):
        checker.has_remaining_drops(10, "123")


def test_filter_games_with_drops_includes_on_errors():
    checker = make_checker(text="")
    checker.has_remaining_drops = Mock(side_effect=[True, False, RuntimeError("x")])

    result = checker.filter_games_with_drops([1, 2, 3], "123")

    assert result == [1, 3]
    checker.detailed_logger.log_api_results.assert_called_once()


def test_has_remaining_drops_includes_ambiguous_authenticated_badge_pages():
    html = """
    <title>Steam Community :: Steam Badges :: LIMBO</title>
    <div class="badge_row depressed badge_gamecard_page">
      <div class="badge_title_stats_drops"></div>
      <div class="badge_card_set_cards"></div>
    </div>
    """
    with patch(
        "steam_idle_bot.steam.card_drops.CardDropChecker._build_session",
        return_value=Sess(html),
    ):
        checker = CardDropChecker(
            make_settings(),
            authenticated_session=True,
        )
    checker.detailed_logger.log_scraping_result = Mock()
    checker._auth_verified = True  # skip the live session probe in this unit test

    assert checker.has_remaining_drops(10, "test_vanity") is True


# ---------------------------------------------------------------------------
# Coverage push: session lifecycle, verify-session downgrade, drop-status
# markers inside the drops div, progress logging, and cache robustness edges
# ---------------------------------------------------------------------------


def test_set_session_swaps_http_and_resets_verification() -> None:
    """set_session swaps the HTTP session, flags authentication and resets the
    cached verification verdict so the new session is re-probed (85-87)."""
    checker = make_checker(text="irrelevant")
    checker._auth_verified = True

    new_session = Sess("page")
    checker.set_session(new_session, authenticated_session=True)

    assert checker._http is new_session
    assert checker.has_authenticated_session is True
    assert checker._auth_verified is None


def test_verify_session_network_failure_returns_false() -> None:
    """Any request failure during the badges/ probe downgrades to False (109-111)."""
    checker = make_checker(exc=requests.exceptions.ConnectionError("down"))
    checker._authenticated_session = True

    assert checker._verify_session("123") is False


def test_ensure_session_verified_quiet_downgrade_logs_info(caplog) -> None:
    """quiet=True logs the downgrade at INFO instead of WARNING (126-127)."""
    # A logged-out badges page: HTTP 200 but no g_steamID / account_pulldown.
    checker = make_checker(text="<html>public badges list</html>")
    checker._authenticated_session = True
    checker._auth_verified = None

    with caplog.at_level("INFO", logger="steam_idle_bot.steam.card_drops"):
        checker._ensure_session_verified("123", quiet=True)

    assert checker.has_authenticated_session is False
    assert checker._auth_verified is False
    assert "attempting recovery" in caplog.text


def test_filter_progress_logged_on_long_scans(tmp_path, caplog) -> None:
    """Scans over 50 games emit periodic progress lines (322-323)."""
    settings = Settings(
        username="user",
        password="pass",
        drop_cache_path=str(tmp_path / "no_drop.json"),
    )
    session = Sess("no card drops remaining")
    with patch("steam_idle_bot.steam.card_drops.CardDropChecker._build_session", return_value=session):
        checker = CardDropChecker(settings)
    checker.detailed_logger.log_api_results = Mock()

    games = list(range(1, 51))  # exactly 50 -> total >= 50, index 50 fires the log
    with caplog.at_level("INFO", logger="steam_idle_bot.steam.card_drops"):
        assert checker.filter_games_with_drops(games, "123") == []

    assert "card-drop scan progress: 50/50 checked" in caplog.text


@pytest.mark.parametrize(
    "drops_div_html,expected",
    [
        # Marker text split by inner tags is invisible to the raw-content scan
        # but recognized after the drops-div is tag-stripped (467-470).
        ('<div class="badge_title_stats_drops">no card drops <b>remaining</b></div>', (False, True)),
        ('<div class="badge_title_stats_drops">pode <b>dar mais</b> cartas</div>', (True, True)),
        # Empty after stripping -> not confident on a badge page (464-466).
        ('<div class="badge_title_stats_drops"><b></b>  </div>', (None, False)),
        # Non-empty but marker-free drops text falls through to the generic checks.
        ('<div class="badge_title_stats_drops">some other stats text</div>', (None, False)),
    ],
)
def test_extract_drop_status_markers_inside_drops_div(drops_div_html: str, expected) -> None:
    checker = make_checker(text="page")
    assert checker._extract_drop_status(drops_div_html, 10) == expected


def test_extract_drop_status_generic_card_content_on_badge_page() -> None:
    """Card-related wording on a badge page without any explicit signal is
    reported as ambiguous, not as a confident no-drop (480-484)."""
    checker = make_checker(text="page")
    html = '<div class="badge_gamecard_page">How do I earn card drops?</div>'

    assert checker._extract_drop_status(html, 10) == (None, False)


def test_remember_no_drop_never_downgrades_trusted_verdict(tmp_path) -> None:
    """A trusted negative stays trusted even if re-observed untrusted (531)."""
    settings = Settings(
        username="user",
        password="pass",
        drop_cache_path=str(tmp_path / "no_drop.json"),
    )
    with patch("steam_idle_bot.steam.card_drops.CardDropChecker._build_session", return_value=Sess()):
        checker = CardDropChecker(settings)

    checker._remember_no_drop("123", 10, trusted=True)
    checker._remember_no_drop("123", 10, trusted=False)

    assert checker._no_drop_cache["123"][10]["trusted"] is True


def test_cached_no_drop_skips_entries_with_unparseable_timestamp(tmp_path) -> None:
    """A corrupt 'ts' value is skipped instead of poisoning the cache read (556-557)."""
    settings = Settings(
        username="user",
        password="pass",
        drop_cache_path=str(tmp_path / "no_drop.json"),
    )
    with patch("steam_idle_bot.steam.card_drops.CardDropChecker._build_session", return_value=Sess()):
        checker = CardDropChecker(settings)

    checker._no_drop_cache["123"] = {
        10: {"ts": time.time(), "trusted": True},
        20: {"ts": "garbage", "trusted": True},
    }

    assert checker._cached_no_drop_ids("123") == {10}


def test_load_no_drop_cache_tolerates_malformed_files(tmp_path) -> None:
    """Every malformed shape is skipped without raising (574-593)."""
    settings = Settings(
        username="user",
        password="pass",
        drop_cache_path=str(tmp_path / "no_drop.json"),
    )

    def _checker_with_file(content: str) -> CardDropChecker:
        Path(settings.drop_cache_path).write_text(content, encoding="utf-8")
        with patch("steam_idle_bot.steam.card_drops.CardDropChecker._build_session", return_value=Sess()):
            return CardDropChecker(settings)

    # Top level is not a dict at all.
    assert _checker_with_file("[1, 2]")._no_drop_cache == {}

    # Mixed buckets: non-dict bucket, non-int app key, non-dict meta, plus one
    # valid entry; only the valid one survives, and the empty bucket is dropped.
    mixed = '{"good": {"30": {"ts": 5, "trusted": true}}, "bad-bucket": 7, "mixed": {"xx": {"ts": 1}, "40": "not-a-dict", "50": {"ts": 2, "trusted": false}}, "empty": {"zz": {"ts": 1}}}'
    checker = _checker_with_file(mixed)
    assert checker._no_drop_cache == {
        "good": {30: {"ts": 5.0, "trusted": True}},
        "mixed": {50: {"ts": 2.0, "trusted": False}},
    }

    # Invalid JSON -> best-effort skip.
    assert _checker_with_file("{not json")._no_drop_cache == {}


def test_save_no_drop_cache_swallows_write_errors(tmp_path, caplog) -> None:
    """An unwritable cache path is logged at debug and never fails the run (606-607)."""
    blocked_dir = tmp_path / "blocked"
    blocked_dir.mkdir()
    settings = Settings(
        username="user",
        password="pass",
        drop_cache_path=str(blocked_dir),  # a directory: open() for write will fail
    )
    with patch("steam_idle_bot.steam.card_drops.CardDropChecker._build_session", return_value=Sess()):
        checker = CardDropChecker(settings)

    checker._remember_no_drop("123", 10, trusted=True)

    with caplog.at_level("DEBUG", logger="steam_idle_bot.steam.card_drops"):
        checker._save_no_drop_cache()  # must not raise

    assert "Failed to save no-drop cache" in caplog.text


def test_build_session_is_real_retrying_requests_session() -> None:
    """The real session factory wires GET-only retries with backoff on both
    schemes (176-188) — a genuine requests.Session, no stubs."""
    from requests.adapters import HTTPAdapter

    session = CardDropChecker._build_session()

    assert isinstance(session, requests.Session)
    for prefix in ("http://", "https://"):
        adapter = session.get_adapter(f"{prefix}example.invalid")
        assert isinstance(adapter, HTTPAdapter)
        retry = adapter.max_retries
        assert retry.total == 5
        assert retry.backoff_factor == 2.0
        assert 429 in retry.status_forcelist
        assert retry.allowed_methods == frozenset({"GET"})


def test_filter_games_with_drops_trusts_cached_positives(tmp_path) -> None:
    """Games confirmed to have drops within the short window are trusted
    without a second scrape (291-292, 518-519)."""
    settings = Settings(
        username="user",
        password="pass",
        drop_cache_path=str(tmp_path / "no_drop.json"),
    )
    session = Sess("2 card drops remaining")
    session.calls = 0
    original_get = session.get

    def _counting_get(*args, **kwargs):
        session.calls += 1  # type: ignore[attr-defined]
        return original_get(*args, **kwargs)

    session.get = _counting_get  # type: ignore[method-assign]
    with patch("steam_idle_bot.steam.card_drops.CardDropChecker._build_session", return_value=session):
        checker = CardDropChecker(settings)
    checker.detailed_logger.log_api_results = Mock()

    assert checker.filter_games_with_drops([10], "123") == [10]
    assert session.calls == 1

    # Second pass within the TTL window: trusted from cache, no new request.
    assert checker.filter_games_with_drops([10], "123") == [10]
    assert session.calls == 1


def test_cached_has_drops_evicts_expired_entries(tmp_path) -> None:
    """Expired positive verdicts are dropped from the map on read (520-523)."""
    settings = Settings(
        username="user",
        password="pass",
        drop_cache_path=str(tmp_path / "no_drop.json"),
    )
    with patch("steam_idle_bot.steam.card_drops.CardDropChecker._build_session", return_value=Sess()):
        checker = CardDropChecker(settings)

    checker._remember_has_drops("123", 10)  # fresh entry
    checker._has_drops_cache["123"][20] = time.time() - (checker._has_drops_cache_ttl + 60)  # expired

    assert checker._cached_has_drops_ids("123") == {10}
    # The expired entry was evicted from the bucket itself.
    assert 20 not in checker._has_drops_cache["123"]


def test_clear_cache_resets_in_memory_state(tmp_path) -> None:
    settings = Settings(
        username="user",
        password="pass",
        drop_cache_path=str(tmp_path / "no_drop.json"),
    )
    with patch("steam_idle_bot.steam.card_drops.CardDropChecker._build_session", return_value=Sess()):
        checker = CardDropChecker(settings)

    checker._remember_no_drop("123", 10, trusted=True)
    checker._remember_has_drops("123", 20)
    checker.clear_cache()

    assert checker._no_drop_cache == {}
    assert checker._has_drops_cache == {}
    assert checker._no_drop_dirty is False
