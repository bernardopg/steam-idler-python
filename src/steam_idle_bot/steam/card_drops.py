"""Web scraping service for checking Steam card drops."""

import logging
import re

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ..config.settings import Settings
from ..utils.detailed_logger import DetailedLogger
from ..utils.exceptions import SteamAPITimeoutError

logger = logging.getLogger(__name__)


class CardDropCheckError(Exception):
    """Raised when there's an error checking card drops."""


class CardDropChecker:
    """Checks Steam card drops using web scraping."""

    def __init__(self, settings: Settings, timeout: int = 10) -> None:
        self.settings = settings
        self.timeout = timeout
        self._http = self._build_session()
        self.detailed_logger = DetailedLogger(settings)

    @staticmethod
    def _build_gamecards_url(steam_id: str, app_id: int) -> str:
        """Build the correct Steam community URL for the badge progress page."""
        cleaned_id = steam_id.strip().strip("/")
        if not cleaned_id:
            raise ValueError("Steam ID cannot be empty")

        # Remove domain prefix if a full URL is provided
        cleaned_id = re.sub(
            r"^https?://steamcommunity\.com/",
            "",
            cleaned_id,
            flags=re.IGNORECASE,
        )

        # Allow callers to pass paths such as "profiles/<id>" or "id/<name>"
        if cleaned_id.startswith(("profiles/", "id/")):
            prefix, _, remainder = cleaned_id.partition("/")
            identifier = remainder.strip("/")
            if not identifier:
                raise ValueError("Steam ID segment cannot be empty")
            return f"https://steamcommunity.com/{prefix}/{identifier}/gamecards/{app_id}/"

        # Detect 64-bit numeric Steam IDs (17 digits) and use the profiles path
        steam64_match = re.search(r"\d{17}", cleaned_id)
        if cleaned_id.isdigit() and len(cleaned_id) >= 17:
            identifier = cleaned_id
            return f"https://steamcommunity.com/profiles/{identifier}/gamecards/{app_id}/"

        if steam64_match:
            identifier = steam64_match.group(0)
            return f"https://steamcommunity.com/profiles/{identifier}/gamecards/{app_id}/"

        # Fallback to vanity URL path
        return f"https://steamcommunity.com/id/{cleaned_id}/gamecards/{app_id}/"

    @staticmethod
    def _build_session() -> requests.Session:
        session = requests.Session()
        retry = Retry(
            total=3,
            allowed_methods=frozenset({"GET"}),
        )
        adapter = HTTPAdapter(max_retries=retry)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session

    def has_remaining_drops(self, app_id: int, steam_id: str) -> bool:
        """
        Check if a game has remaining card drops by scraping the gamecards page.

        Args:
            app_id: Steam app ID to check
            steam_id: Steam ID of the user

        Returns:
            True if the game still has card drops available, False otherwise
        """
        try:
            url = self._build_gamecards_url(steam_id, app_id)

            response = self._http.get(
                url,
                timeout=self.timeout,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                },
            )
            response.raise_for_status()

            content = response.text

            # Look for the exact text patterns in the content
            content_lower = content.lower()

            # Check for "não dará mais cartas" (no drops) - Portuguese
            if "não dará mais cartas" in content_lower:
                result = False
                logger.debug(f"Game {app_id} - NO DROPS (found 'não dará mais cartas')")
            # Check for "pode dar mais" (has drops) - Portuguese
            elif "pode dar mais" in content_lower:
                result = True
                logger.debug(f"Game {app_id} - HAS DROPS (found 'pode dar mais')")
            # Check for English patterns as fallback
            elif "no card drops remaining" in content_lower:
                result = False
                logger.debug(f"Game {app_id} - NO DROPS (found 'no card drops remaining')")
            elif "can drop more" in content_lower or "drops remaining" in content_lower:
                result = True
                logger.debug(f"Game {app_id} - HAS DROPS (found English pattern)")
            else:
                # Try to find the specific span with progress_info_bold
                progress_span_match = re.search(
                    r'<span class="progress_info_bold">([^<]+)</span>',
                    content,
                    re.IGNORECASE
                )

                if progress_span_match:
                    span_text = progress_span_match.group(1).strip().lower()
                    logger.debug(f"Game {app_id} - Found progress span: '{span_text}'")

                    if "não dará mais" in span_text or "no card drops" in span_text:
                        result = False
                        logger.debug(f"Game {app_id} - NO DROPS (span: {span_text})")
                    elif "pode dar mais" in span_text or "drops remaining" in span_text:
                        result = True
                        logger.debug(f"Game {app_id} - HAS DROPS (span: {span_text})")
                    else:
                        # Try to extract numbers from the span to determine if drops remain
                        numbers = re.findall(r'\d+', span_text)
                        if numbers:
                            # If we find numbers like "3/5" or "2 remaining", assume has drops
                            if len(numbers) >= 2 or "remaining" in span_text:
                                result = True
                                logger.debug(f"Game {app_id} - HAS DROPS (numbers found: {numbers})")
                            else:
                                result = False
                                logger.debug(f"Game {app_id} - NO DROPS (single number: {numbers})")
                        else:
                            logger.warning(f"Game {app_id} - Unknown span text: '{span_text}', assuming has drops")
                            result = True  # Fallback
                else:
                    # Try to find other patterns in the HTML
                    # Look for card drop progress indicators
                    if "card drops" in content_lower or "trading cards" in content_lower:
                        # If we can find card-related content but no clear status, assume has drops
                        logger.debug(f"Game {app_id} - Found card-related content but unclear status, assuming has drops")
                        result = True
                    else:
                        logger.warning(f"Could not determine drop status for {app_id}, assuming has drops")
                        result = True  # Fallback

            # Additional check: look for specific Steam card drop patterns
            # Steam often shows "X card drops remaining" or similar
            card_drop_patterns = [
                r'(\d+)\s*card drops? remaining',
                r'(\d+)\s*drops? remaining',
                r'remaining\s*:\s*(\d+)',
                r'progress_info_bold[^>]*>([^<]*(\d+)[^<]*)</span>',
            ]

            for pattern in card_drop_patterns:
                match = re.search(pattern, content, re.IGNORECASE)
                if match:
                    try:
                        drops_remaining = int(match.group(1))
                        if drops_remaining > 0:
                            result = True
                            logger.debug(f"Game {app_id} - HAS DROPS (found {drops_remaining} drops remaining)")
                            break
                        else:
                            result = False
                            logger.debug(f"Game {app_id} - NO DROPS (found {drops_remaining} drops remaining)")
                            break
                    except (ValueError, IndexError):
                        continue

            # Log the scraping result with more details
            self.detailed_logger.log_scraping_result(
                app_id, steam_id, result, content[:500]
            )

            return result

        except requests.exceptions.Timeout as err:
            raise SteamAPITimeoutError(f"Timeout checking card drops for {app_id}") from err
        except requests.exceptions.RequestException as err:
            raise CardDropCheckError(f"Network error checking card drops for {app_id}: {err}") from err
        except Exception as err:
            raise CardDropCheckError(f"Error checking card drops for {app_id}: {err}") from err

    def filter_games_with_drops(
        self, game_ids: list[int], steam_id: str
    ) -> list[int]:
        """
        Filter games to only include those with remaining card drops.

        Args:
            game_ids: List of Steam app IDs to check
            steam_id: Steam ID of the user

        Returns:
            List of game IDs that still have card drops available
        """
        filtered = []
        skipped = 0
        scraping_results = {}

        logger.info(f"Checking card drops for {len(game_ids)} games via web scraping...")

        for app_id in game_ids:
            try:
                has_drops = self.has_remaining_drops(app_id, steam_id)
                scraping_results[app_id] = has_drops

                if has_drops:
                    filtered.append(app_id)
                else:
                    skipped += 1
                    logger.info(f"Filtered out game {app_id} - no remaining drops")

            except Exception as e:
                # If scraping fails, include the game to be safe
                logger.warning(f"Failed to check drops for {app_id}: {e}")
                scraping_results[app_id] = True  # Assume has drops on error
                filtered.append(app_id)

        # Log the complete filtering process
        self.detailed_logger.log_api_results(
            "web_scraping", game_ids, scraping_results
        )

        if skipped:
            logger.info(
                "Filtered out %s games with no card drops remaining via web scraping",
                skipped
            )

        return filtered
