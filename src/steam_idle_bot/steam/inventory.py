"""Steam inventory snapshots for detecting newly dropped trading cards."""

from __future__ import annotations

__all__ = ["InventoryCardDrop", "SteamInventoryError", "SteamTradingCardInventory"]

import logging
import re
from dataclasses import dataclass
from typing import Any

import requests

from ..config.settings import Settings

logger = logging.getLogger(__name__)


class SteamInventoryError(Exception):
    """Raised when Steam inventory data cannot be retrieved or parsed."""


@dataclass(frozen=True)
class InventoryCardDrop:
    """A newly observed Steam trading-card inventory item."""

    asset_id: str
    app_id: int
    name: str
    game_name: str


class SteamTradingCardInventory:
    """Reads Steam community inventory app 753/context 6 trading cards."""

    INVENTORY_APP_ID = 753
    TRADING_CARD_CONTEXT_ID = 6

    def __init__(self, settings: Settings, session: Any, *, timeout: int | None = None) -> None:
        self.settings = settings
        self._http = session
        self.timeout = timeout or settings.api_timeout

    def snapshot(self, steam_id: str) -> dict[str, InventoryCardDrop]:
        """Return current trading-card assets keyed by Steam inventory asset id."""
        cards: dict[str, InventoryCardDrop] = {}
        last_assetid: str | None = None

        while True:
            data = self._fetch_page(steam_id, last_assetid=last_assetid)
            descriptions = self._description_map(data.get("descriptions", []))
            for asset in data.get("assets", []):
                if not isinstance(asset, dict):
                    continue
                asset_id = str(asset.get("assetid") or "")
                if not asset_id:
                    continue
                key = (str(asset.get("classid") or ""), str(asset.get("instanceid") or "0"))
                description = descriptions.get(key)
                if not description:
                    continue
                card = self._card_from_description(asset_id, description)
                if card is not None:
                    cards[asset_id] = card

            if not data.get("more_items"):
                break
            next_assetid = data.get("last_assetid")
            if not next_assetid or str(next_assetid) == last_assetid:
                break
            last_assetid = str(next_assetid)

        return cards

    def new_cards_by_app(self, before: dict[str, InventoryCardDrop], after: dict[str, InventoryCardDrop], active_app_ids: list[int]) -> dict[int, list[InventoryCardDrop]]:
        """Group newly acquired trading cards by app id for the active games."""
        active = set(active_app_ids)
        grouped: dict[int, list[InventoryCardDrop]] = {}
        for asset_id, card in after.items():
            if asset_id in before:
                continue
            if active and card.app_id not in active:
                continue
            grouped.setdefault(card.app_id, []).append(card)
        return grouped

    def _fetch_page(self, steam_id: str, *, last_assetid: str | None = None) -> dict[str, Any]:
        url = f"https://steamcommunity.com/inventory/{steam_id}/{self.INVENTORY_APP_ID}/{self.TRADING_CARD_CONTEXT_ID}"
        # Steam rejects overly large inventory pages with HTTP 400. 2000 is the
        # commonly accepted upper bound for this endpoint.
        params: dict[str, Any] = {"l": "english", "count": 2000}
        if last_assetid:
            params["start_assetid"] = last_assetid
        try:
            response = self._http.get(
                url,
                params=params,
                timeout=self.timeout,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
            )
            response.raise_for_status()
            data = response.json()
        except requests.exceptions.RequestException as err:
            raise SteamInventoryError(f"Network error reading Steam inventory: {err}") from err
        except ValueError as err:
            raise SteamInventoryError("Steam inventory returned invalid JSON") from err

        if not isinstance(data, dict) or data.get("success") not in (1, True):
            raise SteamInventoryError("Steam inventory response was not successful")
        return data

    @staticmethod
    def _description_map(descriptions: Any) -> dict[tuple[str, str], dict[str, Any]]:
        result: dict[tuple[str, str], dict[str, Any]] = {}
        if not isinstance(descriptions, list):
            return result
        for description in descriptions:
            if not isinstance(description, dict):
                continue
            class_id = str(description.get("classid") or "")
            instance_id = str(description.get("instanceid") or "0")
            if class_id:
                result[(class_id, instance_id)] = description
        return result

    @staticmethod
    def _card_from_description(asset_id: str, description: dict[str, Any]) -> InventoryCardDrop | None:
        tags = description.get("tags", [])
        if not isinstance(tags, list):
            return None

        is_trading_card = False
        app_id: int | None = None
        game_name = ""
        for tag in tags:
            if not isinstance(tag, dict):
                continue
            category = tag.get("category")
            internal_name = str(tag.get("internal_name") or "")
            localized_name = str(tag.get("localized_tag_name") or "")
            if category == "item_class" and internal_name == "item_class_2":
                is_trading_card = True
            if category == "Game":
                match = re.fullmatch(r"app_(\d+)", internal_name)
                if match:
                    app_id = int(match.group(1))
                    game_name = localized_name

        if not is_trading_card or app_id is None:
            return None

        return InventoryCardDrop(
            asset_id=asset_id,
            app_id=app_id,
            name=str(description.get("name") or "Unknown card"),
            game_name=game_name,
        )
