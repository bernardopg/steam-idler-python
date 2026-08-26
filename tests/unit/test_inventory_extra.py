"""Additional tests for Steam inventory snapshots: pagination and error paths."""

from __future__ import annotations

import pytest
import requests

from steam_idle_bot.config.settings import Settings
from steam_idle_bot.steam.inventory import SteamInventoryError, SteamTradingCardInventory


class DummyResponse:
    def __init__(self, payload=None, *, json_error=False):
        self.payload = payload
        self.json_error = json_error

    def raise_for_status(self):
        return None

    def json(self):
        if self.json_error:
            raise ValueError("not json")
        return self.payload


class PagedSession:
    """Serves queued page payloads in order and records each request."""

    def __init__(self, pages):
        self.pages = list(pages)
        self.calls: list[dict] = []

    def get(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        page = self.pages.pop(0)
        if isinstance(page, Exception):
            raise page
        return page


def make_inventory(session) -> SteamTradingCardInventory:
    return SteamTradingCardInventory(Settings(username="user", password="pass"), session)


def card_description(app_id: int, name: str = "Card", game: str = "Game") -> dict:
    return {
        "classid": f"class-{app_id}",
        "instanceid": "0",
        "name": name,
        "tags": [
            {"category": "Game", "internal_name": f"app_{app_id}", "localized_tag_name": game},
            {"category": "item_class", "internal_name": "item_class_2", "localized_tag_name": "Trading Card"},
        ],
    }


def make_page(assets: list, descriptions: list, *, more_items: bool = False, last_assetid=None) -> DummyResponse:
    return DummyResponse({"success": 1, "assets": assets, "descriptions": descriptions, "more_items": more_items, "last_assetid": last_assetid})


def test_snapshot_follows_pagination_cursor() -> None:
    page1 = make_page(
        [{"assetid": "a1", "classid": "class-570", "instanceid": "0"}],
        [card_description(570)],
        more_items=True,
        last_assetid="a1",
    )
    page2 = make_page(
        [{"assetid": "b2", "classid": "class-730", "instanceid": "0"}],
        [card_description(730)],
    )
    session = PagedSession([page1, page2])
    inventory = make_inventory(session)

    snapshot = inventory.snapshot("76561198000000000")

    assert sorted(snapshot) == ["a1", "b2"]
    assert snapshot["a1"].app_id == 570
    assert snapshot["b2"].app_id == 730
    # The second request resumed from the cursor of the first page.
    assert len(session.calls) == 2
    assert "start_assetid" not in session.calls[0]
    assert session.calls[1]["params"]["start_assetid"] == "a1"


def test_snapshot_stops_when_cursor_does_not_advance() -> None:
    """A repeated/missing ``last_assetid`` with ``more_items`` breaks the loop
    instead of looping forever on a degenerate payload."""
    page = make_page(
        [{"assetid": "a1", "classid": "class-570", "instanceid": "0"}],
        [card_description(570)],
        more_items=True,
        last_assetid="a1",
    )
    session = PagedSession([page, page])
    inventory = make_inventory(session)

    # First page sets cursor a1; second page returns the same last_assetid -> break.
    snapshot = inventory.snapshot("76561198000000000")

    assert list(snapshot) == ["a1"]
    assert len(session.calls) == 2


def test_snapshot_stops_when_more_items_without_cursor() -> None:
    page = make_page([], [], more_items=True, last_assetid=None)
    session = PagedSession([page])
    inventory = make_inventory(session)

    assert inventory.snapshot("76561198000000000") == {}
    assert len(session.calls) == 1


def test_snapshot_skips_malformed_assets() -> None:
    descriptions = [card_description(570)]
    page = make_page(
        [
            "not-a-dict",  # non-dict entry skipped
            {"classid": "class-570", "instanceid": "0"},  # missing assetid skipped
            {"assetid": "", "classid": "class-570", "instanceid": "0"},  # empty assetid skipped
            {"assetid": "unknown-class", "classid": "nope", "instanceid": "0"},  # no description match
            {"assetid": "ok", "classid": "class-570", "instanceid": "0"},
        ],
        descriptions,
    )
    inventory = make_inventory(PagedSession([page]))

    snapshot = inventory.snapshot("76561198000000000")

    assert list(snapshot) == ["ok"]


def test_fetch_page_network_error_wrapped() -> None:
    session = PagedSession([requests.exceptions.ConnectionError("down")])
    inventory = make_inventory(session)

    with pytest.raises(SteamInventoryError, match="Network error"):
        inventory.snapshot("76561198000000000")


def test_fetch_page_invalid_json_wrapped() -> None:
    session = PagedSession([DummyResponse(json_error=True)])
    inventory = make_inventory(session)

    with pytest.raises(SteamInventoryError, match="invalid JSON"):
        inventory.snapshot("76561198000000000")


def test_fetch_page_unsuccessful_payload_rejected() -> None:
    session = PagedSession([DummyResponse({"success": 0})])
    inventory = make_inventory(session)

    with pytest.raises(SteamInventoryError, match="not successful"):
        inventory.snapshot("76561198000000000")


def test_fetch_page_non_dict_payload_rejected() -> None:
    session = PagedSession([DummyResponse(["a", "b"])])
    inventory = make_inventory(session)

    with pytest.raises(SteamInventoryError, match="not successful"):
        inventory.snapshot("76561198000000000")


def test_fetch_page_passes_timeout_and_headers() -> None:
    page = make_page([], [])
    session = PagedSession([page])
    settings = Settings(username="user", password="pass")
    inventory = SteamTradingCardInventory(settings, session, timeout=13)

    inventory.snapshot("76561198000000000")

    call = session.calls[0]
    assert call["timeout"] == 13
    assert call["url"] == "https://steamcommunity.com/inventory/76561198000000000/753/6"
    assert call["params"] == {"l": "english", "count": 2000}
    assert "User-Agent" in call["headers"]


def test_description_map_skips_malformed_entries() -> None:
    result = SteamTradingCardInventory._description_map(
        [
            "not-a-dict",
            {"instanceid": "0"},  # no classid
            {"classid": "k", "instanceid": "0"},
        ]
    )
    assert result == {("k", "0"): {"classid": "k", "instanceid": "0"}}

    assert SteamTradingCardInventory._description_map("nope") == {}


def test_card_from_description_rejects_non_cards() -> None:
    # tags not a list -> None
    assert SteamTradingCardInventory._card_from_description("a", {"tags": "nope"}) is None

    # no Trading Card item_class tag -> None
    only_game = {"name": "X", "tags": [{"category": "Game", "internal_name": "app_570", "localized_tag_name": "G"}]}
    assert SteamTradingCardInventory._card_from_description("a", only_game) is None

    # card tag but no Game tag (app_id unknown) -> None
    only_card = {"name": "X", "tags": [{"category": "item_class", "internal_name": "item_class_2"}]}
    assert SteamTradingCardInventory._card_from_description("a", only_card) is None

    # non-dict tag entries are skipped; a Game tag not matching app_N is ignored
    weird_game = {
        "name": "X",
        "tags": [
            "not-a-dict",
            {"category": "Game", "internal_name": "profile_570", "localized_tag_name": "G"},
            {"category": "item_class", "internal_name": "item_class_2", "localized_tag_name": "Trading Card"},
            {"category": "Game", "internal_name": "app_570", "localized_tag_name": "Real Game"},
        ],
    }
    card = SteamTradingCardInventory._card_from_description("a", weird_game)
    assert card is not None
    assert card.app_id == 570
    assert card.game_name == "Real Game"
    assert card.name == "X"

    # missing name falls back to a placeholder
    no_name = {"tags": weird_game["tags"]}
    card2 = SteamTradingCardInventory._card_from_description("b", no_name)
    assert card2 is not None
    assert card2.name == "Unknown card"


def test_new_cards_by_app_without_active_filter_keeps_all_apps() -> None:
    """An empty active list means no filtering: every new card is grouped."""
    from steam_idle_bot.steam.inventory import InventoryCardDrop

    inventory = make_inventory(PagedSession([]))
    before = {}
    after = {
        "x": InventoryCardDrop(asset_id="x", app_id=1, name="A", game_name="G"),
        "y": InventoryCardDrop(asset_id="y", app_id=2, name="B", game_name="G"),
    }

    grouped = inventory.new_cards_by_app(before, after, [])

    assert sorted(grouped) == [1, 2]
