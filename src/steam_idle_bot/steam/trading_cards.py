"""Trading card detection and management."""

import json
import logging
import os
import time
from typing import Any, Optional

import requests
from requests import Session
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ..utils.exceptions import SteamAPITimeoutError, TradingCardDetectionError

logger = logging.getLogger(__name__)


class TradingCardDetector:
    """Handles detection of Steam games with trading cards."""

    # Steam category ID for trading cards
    TRADING_CARDS_CATEGORY_ID = 29

    def __init__(
        self,
        timeout: int = 10,
        rate_limit_delay: float = 0.5,
        cache_enabled: bool = True,
        cache_path: str = ".cache/trading_cards.json",
        cache_ttl_days: int = 30,
        session: Optional[Any] = None,
    ):
        self.timeout = timeout
        self.rate_limit_delay = rate_limit_delay
        self.cache_enabled = cache_enabled
        self.cache_path = cache_path
        self.cache_ttl_days = cache_ttl_days

        # HTTP interface: default to requests module for test compatibility
        self._http = session or requests

        # In-memory caches
        self._cache: dict[int, bool] = {}
        self._cache_data: dict[int, tuple[bool, float]] = {}

        # Load persisted cache
        if self.cache_enabled:
            self._load_cache()

    def has_trading_cards(self, app_id: int) -> bool:
        """
        Check if a game has trading cards by querying Steam store API.

        Args:
            app_id: Steam app ID to check

        Returns:
            True if the game has trading cards, False otherwise

        Raises:
            TradingCardDetectionError: If unable to determine trading card status
            SteamAPITimeoutError: If the request times out
        """
        if app_id in self._cache:
            return self._cache[app_id]

        try:
            url = "https://store.steampowered.com/api/appdetails"
            params = {"appids": app_id, "filters": "categories"}

            response = self._http.get(
                url,
                params=params,
                timeout=self.timeout,
                headers={"User-Agent": "Steam-Idle-Bot/1.0"},
            )
            response.raise_for_status()

            data = response.json()

            if str(app_id) not in data or not data[str(app_id)]["success"]:
                raise TradingCardDetectionError(
                    f"Failed to get app details for {app_id}"
                )

            categories = data[str(app_id)].get("data", {}).get("categories", [])
            has_cards = any(
                cat.get("id") == self.TRADING_CARDS_CATEGORY_ID for cat in categories
            )

            self._remember(app_id, has_cards)
            return has_cards

        except (requests.exceptions.Timeout, TimeoutError) as err:
            raise SteamAPITimeoutError(
                f"Timeout checking trading cards for app {app_id}"
            ) from err
        except requests.exceptions.RequestException as err:
            raise TradingCardDetectionError(
                f"Network error checking trading cards for app {app_id}: {err}"
            ) from err
        except Exception as err:  # noqa: BLE001 - broad for resilience
            raise TradingCardDetectionError(
                f"Error checking trading cards for app {app_id}: {err}"
            ) from err

    def filter_games_with_trading_cards(
        self,
        game_ids: list[int],
        max_games: int = 30,
        *,
        max_checks: Optional[int] = None,
        skip_failures: bool = False,
    ) -> list[int]:
        """
        Filter games to only include those with trading cards.

        Args:
            game_ids: List of Steam app IDs to filter
            max_games: Maximum number of games to return

        Returns:
            List of game IDs that have trading cards
        """
        filtered_games = []

        checks = 0
        for _i, game_id in enumerate(game_ids):
            try:
                if self.has_trading_cards(game_id):
                    filtered_games.append(game_id)
                    if len(filtered_games) >= max_games:
                        break

                # Rate limiting
                time.sleep(self.rate_limit_delay)
                checks += 1
                if max_checks is not None and checks >= max_checks:
                    break

            except KeyboardInterrupt:
                break
            except TradingCardDetectionError as e:
                # Store API often returns unsuccessful for DLC/retired apps.
                # Treat as no-cards and keep noise low.
                if not skip_failures:
                    logger.debug(
                        f"Trading card detection failed for app {game_id}: {e}"
                    )
                continue
            except SteamAPITimeoutError as e:
                logger.warning(
                    f"Timeout checking trading cards for game {game_id}: {e}"
                )
                continue
            except Exception as e:
                if not skip_failures:
                    logger.info(f"Error checking trading cards for game {game_id}: {e}")
                continue

        # Persist cache after batch
        if self.cache_enabled:
            self._save_cache()

        return filtered_games[:max_games]

    def clear_cache(self) -> None:
        """Clear the trading cards cache."""
        self._cache.clear()
        self._cache_data.clear()

    def get_cache_stats(self) -> dict:
        """Get cache statistics."""
        return {
            "cached_games": len(self._cache),
            "games_with_cards": sum(1 for v in self._cache.values() if v),
            "games_without_cards": sum(1 for v in self._cache.values() if not v),
        }

    @staticmethod
    def build_session() -> Session:
        """Build a requests session with retries/backoff."""
        session = requests.Session()
        retry = Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET"}),
        )
        adapter = HTTPAdapter(max_retries=retry)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session

    # Internal cache helpers
    def _remember(self, app_id: int, has_cards: bool) -> None:
        ts = time.time()
        self._cache[app_id] = has_cards
        self._cache_data[app_id] = (has_cards, ts)

    def _load_cache(self) -> None:
        try:
            if not os.path.exists(self.cache_path):
                return
            with open(self.cache_path, encoding="utf-8") as f:
                raw = json.load(f)
            now = time.time()
            ttl_seconds = self.cache_ttl_days * 86400
            for k, v in raw.items():
                try:
                    app_id = int(k)
                    has_cards = bool(v.get("has_cards"))
                    ts = float(v.get("ts", 0))
                    if now - ts <= ttl_seconds:
                        self._cache[app_id] = has_cards
                        self._cache_data[app_id] = (has_cards, ts)
                except Exception:
                    continue
        except Exception as e:
            logger.debug(f"Failed to load trading card cache: {e}")

    def _save_cache(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.cache_path) or ".", exist_ok=True)
            out: dict[str, dict[str, Any]] = {}
            for app_id, (has_cards, ts) in self._cache_data.items():
                out[str(app_id)] = {"has_cards": has_cards, "ts": ts}
            with open(self.cache_path, "w", encoding="utf-8") as f:
                json.dump(out, f)
        except Exception as e:
            logger.debug(f"Failed to save trading card cache: {e}")
