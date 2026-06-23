"""Trading card detection and management."""

__all__ = ["TradingCardDetector"]

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

import requests
from requests import Session
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ..utils.exceptions import (
    RateLimitError,
    SteamAPITimeoutError,
    TradingCardDetectionError,
)

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
        session: Any | None = None,
    ):
        self.timeout = timeout
        self.rate_limit_delay = rate_limit_delay
        self.cache_enabled = cache_enabled
        self.cache_path = Path(cache_path)
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
                # Steam returns unsuccessful responses for some DLC/retired apps.
                # Treat those as "no trading cards" and cache the result to avoid
                # retrying the same known misses on every refresh cycle.
                self._remember(app_id, False)
                return False

            categories = data[str(app_id)].get("data", {}).get("categories", [])
            has_cards = any(cat.get("id") == self.TRADING_CARDS_CATEGORY_ID for cat in categories)

            self._remember(app_id, has_cards)
            return has_cards

        except (requests.exceptions.Timeout, TimeoutError) as err:
            raise SteamAPITimeoutError(f"Timeout checking trading cards for app {app_id}") from err
        except requests.exceptions.RetryError as err:
            # Raised once the session's retry budget is exhausted, typically after
            # repeated 429s from the Steam store API.
            raise RateLimitError(f"Steam rate limit (429) checking trading cards for app {app_id}") from err
        except requests.exceptions.HTTPError as err:
            status = getattr(getattr(err, "response", None), "status_code", None)
            if status == 429:
                raise RateLimitError(f"Steam rate limit (429) checking trading cards for app {app_id}") from err
            raise TradingCardDetectionError(f"Network error checking trading cards for app {app_id}: {err}") from err
        except requests.exceptions.RequestException as err:
            raise TradingCardDetectionError(f"Network error checking trading cards for app {app_id}: {err}") from err
        except Exception as err:  # noqa: BLE001 - broad for resilience
            raise TradingCardDetectionError(f"Error checking trading cards for app {app_id}: {err}") from err

    def filter_games_with_trading_cards(
        self,
        game_ids: list[int],
        max_games: int = 30,
        *,
        max_checks: int | None = None,
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

        # Adaptive throttle: start at the configured delay, widen it when Steam
        # returns 429s, and relax it again after a streak of clean lookups. This
        # keeps periodic refreshes fast while surviving large libraries that would
        # otherwise exhaust the store API's rate limit.
        base_delay = max(self.rate_limit_delay, 0.0)
        current_delay = base_delay
        max_delay = max(base_delay * 16, 8.0)
        consecutive_ok = 0

        checks = 0
        for _i, game_id in enumerate(game_ids):
            try:
                was_cached = game_id in self._cache
                if self.has_trading_cards(game_id):
                    filtered_games.append(game_id)
                    if len(filtered_games) >= max_games:
                        break

                # Only rate limit actual network lookups. Cached results should be
                # effectively free so periodic refreshes stay fast.
                if not was_cached:
                    time.sleep(current_delay)
                    checks += 1
                    consecutive_ok += 1
                    if consecutive_ok >= 10 and current_delay > base_delay:
                        current_delay = max(base_delay, current_delay / 2)
                        consecutive_ok = 0
                if max_checks is not None and checks >= max_checks:
                    break

            except KeyboardInterrupt:
                break
            except RateLimitError:
                # Steam is throttling. Widen the gap between checks and cool down
                # before moving on so subsequent lookups can recover.
                consecutive_ok = 0
                current_delay = min(max(current_delay * 2, base_delay, 1.0), max_delay)
                checks += 1
                logger.warning(
                    "Steam rate limit hit on app %s; backing off to %.1fs between checks",
                    game_id,
                    current_delay,
                )
                time.sleep(current_delay)
                if max_checks is not None and checks >= max_checks:
                    break
                continue
            except TradingCardDetectionError as e:
                # Store API often returns unsuccessful for DLC/retired apps.
                # Treat as no-cards and keep noise low.
                if not skip_failures:
                    logger.debug(f"Trading card detection failed for app {game_id}: {e}")
                continue
            except SteamAPITimeoutError as e:
                logger.warning(f"Timeout checking trading cards for game {game_id}: {e}")
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
        """Build a requests session with resilient retries/backoff for Steam rate limits."""
        session = requests.Session()
        retry = Retry(
            total=5,
            backoff_factor=2.0,  # 2s, 4s, 8s, 16s, 32s (capped) between retries
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET"}),
            respect_retry_after_header=True,  # honor Steam's Retry-After header
        )
        # Cap a single request's per-retry backoff so we never block for minutes.
        retry.backoff_max = 30.0
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
            if not self.cache_path.exists():
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
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            out: dict[str, dict[str, Any]] = {}
            for app_id, (has_cards, ts) in self._cache_data.items():
                out[str(app_id)] = {"has_cards": has_cards, "ts": ts}
            with open(self.cache_path, "w", encoding="utf-8") as f:
                json.dump(out, f)
        except Exception as e:
            logger.debug(f"Failed to save trading card cache: {e}")
