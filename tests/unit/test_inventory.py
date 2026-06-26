"""Tests for Steam trading-card inventory snapshots."""

from __future__ import annotations

from steam_idle_bot.config.settings import Settings
from steam_idle_bot.steam.inventory import InventoryCardDrop, SteamTradingCardInventory


class DummyResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class DummySession:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return DummyResponse(self.payload)


def make_settings() -> Settings:
    return Settings(username="user", password="pass")


def test_snapshot_extracts_trading_card_assets_by_app_id(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    payload = {
        "success": 1,
        "more_items": False,
        "assets": [
            {"assetid": "asset-card", "classid": "class-card", "instanceid": "0"},
            {"assetid": "asset-gem", "classid": "class-gem", "instanceid": "0"},
        ],
        "descriptions": [
            {
                "classid": "class-card",
                "instanceid": "0",
                "name": "Hunted",
                "tags": [
                    {"category": "Game", "internal_name": "app_311210", "localized_tag_name": "Call of Duty: Black Ops III"},
                    {"category": "item_class", "internal_name": "item_class_2", "localized_tag_name": "Trading Card"},
                ],
            },
            {
                "classid": "class-gem",
                "instanceid": "0",
                "name": "Gems",
                "tags": [
                    {"category": "Game", "internal_name": "app_753", "localized_tag_name": "Steam"},
                    {"category": "item_class", "internal_name": "item_class_7", "localized_tag_name": "Gems"},
                ],
            },
        ],
    }
    inventory = SteamTradingCardInventory(make_settings(), DummySession(payload))

    snapshot = inventory.snapshot("76561198000000000")

    assert list(snapshot) == ["asset-card"]
    card = snapshot["asset-card"]
    assert card.app_id == 311210
    assert card.name == "Hunted"
    assert card.game_name == "Call of Duty: Black Ops III"


def test_new_cards_by_app_filters_to_active_games(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    inventory = SteamTradingCardInventory(make_settings(), DummySession({"success": 1, "assets": [], "descriptions": []}))
    old = InventoryCardDrop(asset_id="old", app_id=311210, name="Old", game_name="Game")
    new_active = InventoryCardDrop(asset_id="new-active", app_id=311210, name="New Active", game_name="Game")
    new_other = InventoryCardDrop(asset_id="new-other", app_id=999, name="New Other", game_name="Other")
    before = {"old": old}
    after = {
        **before,
        "new-active": new_active,
        "new-other": new_other,
    }

    grouped = inventory.new_cards_by_app(before, after, [311210])

    assert list(grouped) == [311210]
    assert [card.name for card in grouped[311210]] == ["New Active"]
