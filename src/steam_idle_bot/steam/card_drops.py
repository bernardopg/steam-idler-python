"""Web scraping service for checking Steam card drops."""

import logging
import re
from typing import Any

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

    def __init__(
        self,
        settings: Settings,
        timeout: int = 10,
        session: Any | None = None,
        *,
        authenticated_session: bool = False,
    ) -> None:
        self.settings = settings
        self.timeout = timeout
        self._http = session or self._build_session()
        self._authenticated_session = authenticated_session
        self.detailed_logger = DetailedLogger(settings)

    @property
    def has_authenticated_session(self) -> bool:
        """Whether the checker is using an authenticated web session."""
        return self._authenticated_session

    def set_session(self, session: Any, *, authenticated_session: bool = False) -> None:
        """Swap the underlying HTTP session, optionally marking it as authenticated."""
        self._http = session
        self._authenticated_session = authenticated_session

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
            total=5,
            backoff_factor=2.0,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET"}),
            respect_retry_after_header=True,
        )
        retry.backoff_max = 30.0
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
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
            )
            response.raise_for_status()

            content = response.text
            result = self._extract_drop_status(content, app_id)
            if result is None:
                if self._authenticated_session:
                    logger.info(
                        "Game %s - badge page status is ambiguous; including game because the session is authenticated",
                        app_id,
                    )
                    result = True
                else:
                    logger.info(
                        "Game %s - badge page status is ambiguous without authenticated session; excluding game",
                        app_id,
                    )
                    result = False

            # Log the scraping result with more details
            self.detailed_logger.log_scraping_result(app_id, steam_id, result, content[:500])

            return result

        except requests.exceptions.Timeout as err:
            raise SteamAPITimeoutError(f"Timeout checking card drops for {app_id}") from err
        except requests.exceptions.RequestException as err:
            raise CardDropCheckError(f"Network error checking card drops for {app_id}: {err}") from err
        except Exception as err:
            raise CardDropCheckError(f"Error checking card drops for {app_id}: {err}") from err

    def filter_games_with_drops(self, game_ids: list[int], steam_id: str) -> list[int]:
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
        self.detailed_logger.log_api_results("web_scraping", game_ids, scraping_results)  # type: ignore[arg-type]

        if skipped:
            logger.info(
                "Filtered out %s games with no card drops remaining via web scraping",
                skipped,
            )

        return filtered

    def _extract_drop_status(self, content: str, app_id: int) -> bool | None:
        """Extract a drop-status signal from the badge HTML.

        Returns:
            True when the page explicitly indicates drops remain.
            False when the page explicitly indicates there are no drops remaining.
            None when the page is valid but ambiguous.
        """
        content_lower = content.lower()
        looks_like_badge_page = any(
            marker in content_lower
            for marker in (
                "badge_gamecard_page",
                "badge_title_stats_drops",
                "badge_card_set_cards",
                "steam badges ::",
            )
        )

        explicit_no_drop_markers = (
            "não dará mais cartas",
            "no card drops remaining",
        )
        explicit_has_drop_markers = (
            "pode dar mais",
            "can drop more",
        )

        for marker in explicit_no_drop_markers:
            if marker in content_lower:
                logger.debug("Game %s - NO DROPS (found marker %r)", app_id, marker)
                return False

        for marker in explicit_has_drop_markers:
            if marker in content_lower:
                logger.debug("Game %s - HAS DROPS (found marker %r)", app_id, marker)
                return True

        card_drop_patterns = [
            r"(\d+)\s*card drops? remaining",
            r"(\d+)\s*drops? remaining",
            r"remaining\s*:\s*(\d+)",
        ]
        for pattern in card_drop_patterns:
            match = re.search(pattern, content, re.IGNORECASE)
            if not match:
                continue
            try:
                drops_remaining = int(match.group(1))
            except (ValueError, IndexError):
                continue

            logger.debug(
                "Game %s - %s DROPS (found %s drops remaining)",
                app_id,
                "HAS" if drops_remaining > 0 else "NO",
                drops_remaining,
            )
            return drops_remaining > 0

        progress_span_match = re.search(
            r'<span class="progress_info_bold">([^<]+)</span>',
            content,
            re.IGNORECASE,
        )
        if progress_span_match:
            span_text = progress_span_match.group(1).strip().lower()
            logger.debug("Game %s - Found progress span: %r", app_id, span_text)

            if "não dará mais" in span_text or "no card drops" in span_text:
                return False
            if "pode dar mais" in span_text or "drops remaining" in span_text:
                return True

            numbers = re.findall(r"\d+", span_text)
            if len(numbers) >= 2 or "remaining" in span_text:
                logger.debug("Game %s - HAS DROPS (progress span numbers: %s)", app_id, numbers)
                return True

            logger.warning(
                "Game %s - Unclear progress span %r, treating as unknown",
                app_id,
                span_text,
            )
            return None

        drops_div_match = re.search(
            r'<div class="badge_title_stats_drops">(.*?)</div>',
            content,
            re.IGNORECASE | re.DOTALL,
        )
        if drops_div_match:
            drops_text = re.sub(r"<[^>]+>", " ", drops_div_match.group(1))
            drops_text = re.sub(r"\s+", " ", drops_text).strip().lower()
            if not drops_text:
                logger.info("Game %s - badge page exposed no drop-status text", app_id)
                return None if looks_like_badge_page else False
            if any(marker in drops_text for marker in explicit_no_drop_markers):
                return False
            if any(marker in drops_text for marker in explicit_has_drop_markers):
                return True

        if ("sign in" in content_lower or "login" in content_lower) and not looks_like_badge_page:
            logger.info(
                "Game %s - badge page appears unauthenticated and exposed no drop status; assuming no drops",
                app_id,
            )
            return False

        if ("card drops" in content_lower or "trading cards" in content_lower) and looks_like_badge_page:
            logger.info(
                "Game %s - found generic card-related content without explicit drop status",
                app_id,
            )
            return None

        logger.warning("Could not determine drop status for %s", app_id)
        return None if looks_like_badge_page else False
