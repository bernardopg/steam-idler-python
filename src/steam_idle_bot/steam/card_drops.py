"""Web scraping service for checking Steam card drops."""

__all__ = ["CardDropCheckError", "CardDropChecker"]

import json
import logging
import re
import time
from pathlib import Path
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

        # Persistent "no remaining drops" cache. A game confirmed to have no
        # remaining card drops never regains them, so we record that verdict and
        # skip re-scraping it on subsequent runs. Keyed by Steam ID.
        # Structure: {steam_id: {app_id: {"ts": float, "trusted": bool}}}
        self.cache_enabled = getattr(settings, "enable_card_cache", True)
        self.cache_path = Path(getattr(settings, "drop_cache_path", ".cache/no_drop_cards.json"))
        self.cache_ttl_days = getattr(settings, "drop_cache_ttl_days", 90)
        self._no_drop_cache: dict[str, dict[int, dict[str, Any]]] = {}
        self._no_drop_dirty = False
        # Cards-remaining counts parsed from badge pages during the last scrape,
        # used to populate the status panel / session report when the badge API
        # has no data (common once a profile's badges are all completed).
        self._drop_counts: dict[int, int] = {}
        if self.cache_enabled:
            self._load_no_drop_cache()

        # Short-lived cache of games confirmed to still have drops. Card-drop
        # filtering re-runs every few minutes during a session; a game that
        # has drops now will not drain between two refresh cycles (drops arrive
        # over hours), so re-scraping the same badge pages every cycle wastes
        # HTTP requests. The TTL is deliberately short so a drained game is
        # detected within one window. Keyed by normalized Steam ID.
        self._has_drops_cache: dict[str, dict[int, float]] = {}
        self._has_drops_cache_ttl: float = 300.0  # 5 minutes

        # Whether the supplied session was actually verified as logged in against
        # steamcommunity.com. ``None`` means "not yet probed".
        self._auth_verified: bool | None = None

    @property
    def has_authenticated_session(self) -> bool:
        """Whether the checker is using an authenticated web session."""
        return self._authenticated_session

    @property
    def drop_counts(self) -> dict[int, int]:
        """Cards-remaining counts parsed from badge pages during scraping."""
        return self._drop_counts

    def set_session(self, session: Any, *, authenticated_session: bool = False) -> None:
        """Swap the underlying HTTP session, optionally marking it as authenticated."""
        self._auth_verified = None
        self._http = session
        self._authenticated_session = authenticated_session

    def _verify_session(self, steam_id: str) -> bool:
        """Probe steamcommunity to confirm the session is genuinely logged in.

        A built session object does not guarantee an authenticated session: a
        store-only / expired token still returns HTTP 200 logged-out pages, on
        which every badge page looks ambiguous. Steam sets ``g_steamID`` to the
        logged-in account's 64-bit id, or ``false`` when signed out — a reliable
        discriminator.
        """
        try:
            base = self._build_gamecards_url(steam_id, 0).rsplit("/gamecards/", 1)[0]
            url = f"{base}/badges/"
            response = self._http.get(
                url,
                timeout=self.timeout,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
            )
            response.raise_for_status()
            content = response.text
            return bool(re.search(r'g_steamID\s*=\s*"\d{17}"', content)) or "account_pulldown" in content
        except Exception as err:  # noqa: BLE001 - probe is best-effort
            logger.debug("Session verification request failed: %s", err)
            return False

    def _ensure_session_verified(self, steam_id: str, *, quiet: bool = False) -> None:
        """Verify the session once; downgrade and warn if not truly authenticated.

        With ``quiet=True`` a failed probe logs at INFO (caller is about to
        attempt recovery and will warn itself if that also fails).
        """
        if not self._authenticated_session or self._auth_verified is not None:
            return

        self._auth_verified = self._verify_session(steam_id)
        if not self._auth_verified:
            self._authenticated_session = False
            if quiet:
                logger.info("Steam web session is not authenticated against steamcommunity.com; attempting recovery from browser cookies...")
                return
            logger.warning(
                "Steam web session is NOT authenticated against steamcommunity.com "
                "(store-only/expired cookies?). Card-drop detection is unreliable: "
                "games with unknown status will be EXCLUDED to avoid idling drained "
                "games. Provide valid community STEAM_WEB_COOKIES or use "
                "IDLING_BACKEND=python to enable accurate drop filtering."
            )
        else:
            logger.info("Verified authenticated steamcommunity session for card-drop checks")

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
        self._ensure_session_verified(steam_id)
        try:
            url = self._build_gamecards_url(steam_id, app_id)

            response = self._http.get(
                url,
                timeout=self.timeout,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
            )
            response.raise_for_status()

            content = response.text
            count = self._extract_drops_remaining(content)
            if count is not None:
                self._drop_counts[app_id] = count
            result, confident = self._extract_drop_status(content, app_id)
            if result is None:
                confident = False
                if self._authenticated_session:
                    logger.debug(
                        "Game %s - badge page status is ambiguous; including game because the session is authenticated",
                        app_id,
                    )
                    result = True
                else:
                    logger.debug(
                        "Game %s - badge page status is ambiguous without authenticated session; excluding game",
                        app_id,
                    )
                    result = False

            # A confirmed "no remaining drops" verdict is permanent, so persist it
            # and skip re-scraping the game on future runs. We also remember weak
            # (unauthenticated/ambiguous) negatives, but tag them so an authenticated
            # run later re-checks them instead of trusting the guess forever.
            if result is False:
                trusted = confident or self._authenticated_session
                self._remember_no_drop(steam_id, app_id, trusted)

            # A confirmed "has drops" verdict is valid only for a short window —
            # the game can drain while idling — so cache it briefly to avoid
            # re-scraping the same badge page on every refresh cycle.
            if result is True:
                self._remember_has_drops(steam_id, app_id)

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

        # Confirm the session is genuinely authenticated before trusting verdicts.
        self._ensure_session_verified(steam_id)

        # Skip games we already confirmed have no remaining drops on a prior run.
        cached_no_drop = self._cached_no_drop_ids(steam_id)
        # Games recently confirmed to still have drops are trusted for a short
        # window, avoiding a redundant scrape of their badge page every cycle.
        cached_has_drops = self._cached_has_drops_ids(steam_id)

        filtered = [app_id for app_id in game_ids if app_id in cached_has_drops]
        cached_hits = len(filtered)
        to_check = [app_id for app_id in game_ids if app_id not in cached_no_drop and app_id not in cached_has_drops]
        cached_skipped = len(game_ids) - len(to_check) - cached_hits
        if cached_skipped:
            logger.info(
                "Skipping %s games already confirmed without drops on a previous run (cached)",
                cached_skipped,
            )
        if cached_hits:
            logger.info(
                "Trusting %s games still have drops (confirmed within the last %.0f min cache window)",
                cached_hits,
                self._has_drops_cache_ttl / 60.0,
            )

        total = len(to_check)
        if total:
            logger.info("Checking card drops for %s games via web scraping...", total)
        else:
            logger.info("All candidate games resolved from cache; no scraping needed")

        for index, app_id in enumerate(to_check, start=1):
            try:
                has_drops = self.has_remaining_drops(app_id, steam_id)
                scraping_results[app_id] = has_drops

                if has_drops:
                    filtered.append(app_id)
                else:
                    skipped += 1
                    logger.debug("Filtered out game %s - no remaining drops", app_id)

            except Exception as e:
                # If scraping fails, include the game to be safe
                logger.warning(f"Failed to check drops for {app_id}: {e}")
                scraping_results[app_id] = True  # Assume has drops on error
                filtered.append(app_id)

            # Periodic progress so long scans are not silent.
            if total >= 50 and (index % 50 == 0 or index == total):
                logger.info("  card-drop scan progress: %s/%s checked", index, total)

        # Persist any newly confirmed no-drop verdicts for future runs.
        self._save_no_drop_cache()

        # Log the complete filtering process
        self.detailed_logger.log_api_results("web_scraping", game_ids, scraping_results)  # type: ignore[arg-type]

        if skipped:
            logger.info(
                "Filtered out %s games with no card drops remaining via web scraping",
                skipped,
            )

        return filtered

    @staticmethod
    def _extract_drops_remaining(content: str) -> int | None:
        """Parse the number of card drops remaining from a badge page.

        Handles Steam's localized progress text, e.g. "Jogo pode dar mais 3 cartas"
        (pt-BR) or "N card drops remaining" (en). Returns 0 when the page explicitly
        states no drops remain, or None when no count is present.
        """
        count_patterns = (
            r"pode dar mais\s+(\d+)\s+cartas?",
            r"can drop\s+(\d+)\s+more",
            r"(\d+)\s*card drops?\s*remaining",
            r"(\d+)\s*drops?\s*remaining",
            r"remaining\s*:\s*(\d+)",
        )
        for pattern in count_patterns:
            match = re.search(pattern, content, re.IGNORECASE)
            if match:
                try:
                    return int(match.group(1))
                except (TypeError, ValueError):
                    continue

        low = content.lower()
        if "não dará mais" in low or "no card drops remaining" in low:
            return 0
        return None

    def _extract_drop_status(self, content: str, app_id: int) -> tuple[bool | None, bool]:
        """Extract a drop-status signal from the badge HTML.

        Returns a ``(status, confident)`` tuple where ``status`` is:
            True when the page indicates drops remain.
            False when the page indicates there are no drops remaining.
            None when the page is valid but ambiguous.
        ``confident`` is True only when the verdict comes from an explicit Steam
        signal (marker text or a numeric drop count), as opposed to a heuristic
        guess. Only confident negatives are safe to cache permanently.
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
                return False, True

        for marker in explicit_has_drop_markers:
            if marker in content_lower:
                logger.debug("Game %s - HAS DROPS (found marker %r)", app_id, marker)
                return True, True

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
            return drops_remaining > 0, True

        progress_span_match = re.search(
            r'<span class="progress_info_bold">([^<]+)</span>',
            content,
            re.IGNORECASE,
        )
        if progress_span_match:
            span_text = progress_span_match.group(1).strip().lower()
            logger.debug("Game %s - Found progress span: %r", app_id, span_text)

            if "não dará mais" in span_text or "no card drops" in span_text:
                return False, True
            if "pode dar mais" in span_text or "drops remaining" in span_text:
                return True, True

            numbers = re.findall(r"\d+", span_text)
            if len(numbers) >= 2 or "remaining" in span_text:
                logger.debug("Game %s - HAS DROPS (progress span numbers: %s)", app_id, numbers)
                return True, True

            logger.debug(
                "Game %s - Unclear progress span %r, treating as unknown",
                app_id,
                span_text,
            )
            return None, False

        drops_div_match = re.search(
            r'<div class="badge_title_stats_drops">(.*?)</div>',
            content,
            re.IGNORECASE | re.DOTALL,
        )
        if drops_div_match:
            drops_text = re.sub(r"<[^>]+>", " ", drops_div_match.group(1))
            drops_text = re.sub(r"\s+", " ", drops_text).strip().lower()
            if not drops_text:
                logger.debug("Game %s - badge page exposed no drop-status text", app_id)
                return (None, False) if looks_like_badge_page else (False, False)
            if any(marker in drops_text for marker in explicit_no_drop_markers):
                return False, True
            if any(marker in drops_text for marker in explicit_has_drop_markers):
                return True, True

        if ("sign in" in content_lower or "login" in content_lower) and not looks_like_badge_page:
            logger.debug(
                "Game %s - badge page appears unauthenticated and exposed no drop status; assuming no drops",
                app_id,
            )
            return False, False

        if ("card drops" in content_lower or "trading cards" in content_lower) and looks_like_badge_page:
            logger.debug(
                "Game %s - found generic card-related content without explicit drop status",
                app_id,
            )
            return None, False

        logger.debug("Could not determine drop status for %s", app_id)
        return (None, False) if looks_like_badge_page else (False, False)

    # ------------------------------------------------------------------
    # No-drop persistence helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _normalize_steam_id(steam_id: str) -> str:
        """Normalize a Steam ID to a stable cache key (prefer the 64-bit id)."""
        text = str(steam_id).strip()
        match = re.search(r"\d{17}", text)
        if match:
            return match.group(0)
        return text.strip("/").lower()

    def clear_cache(self) -> None:
        """Drop the in-memory no-drop cache (does not remove the on-disk file)."""
        self._no_drop_cache.clear()
        self._no_drop_dirty = False
        self._has_drops_cache.clear()

    def _remember_has_drops(self, steam_id: str, app_id: int) -> None:
        """Record a short-lived positive verdict so the next filter cycle skips the scrape."""
        key = self._normalize_steam_id(steam_id)
        self._has_drops_cache.setdefault(key, {})[app_id] = time.time()

    def _cached_has_drops_ids(self, steam_id: str) -> set[int]:
        """Return app IDs confirmed to still have drops within the cache window."""
        key = self._normalize_steam_id(steam_id)
        bucket = self._has_drops_cache.get(key)
        if not bucket:
            return set()
        now = time.time()
        result = {app_id for app_id, ts in bucket.items() if now - ts < self._has_drops_cache_ttl}
        # Opportunistically evict expired entries to keep the map bounded.
        if len(result) != len(bucket):
            self._has_drops_cache[key] = {app_id: ts for app_id, ts in bucket.items() if now - ts < self._has_drops_cache_ttl}
        return result

    def _remember_no_drop(self, steam_id: str, app_id: int, trusted: bool) -> None:
        key = self._normalize_steam_id(steam_id)
        bucket = self._no_drop_cache.setdefault(key, {})
        existing = bucket.get(app_id)
        # Never downgrade a trusted verdict to an untrusted one.
        if existing and existing.get("trusted") and not trusted:
            trusted = True
        bucket[app_id] = {"ts": time.time(), "trusted": bool(trusted)}
        self._no_drop_dirty = True

    def _cached_no_drop_ids(self, steam_id: str) -> set[int]:
        """Return app IDs known to have no remaining drops for this account.

        Entries past the TTL are ignored (and will be re-checked). Weak
        (untrusted) negatives are re-checked once an authenticated session is
        available, so a fixed login can recover wrongly-excluded games.
        """
        if not self.cache_enabled:
            return set()

        key = self._normalize_steam_id(steam_id)
        entries = self._no_drop_cache.get(key, {})
        if not entries:
            return set()

        now = time.time()
        ttl_seconds = self.cache_ttl_days * 86400
        result: set[int] = set()
        for app_id, meta in entries.items():
            try:
                ts = float(meta.get("ts", 0))
            except (TypeError, ValueError):
                continue
            if now - ts > ttl_seconds:
                continue
            trusted = bool(meta.get("trusted"))
            if self._authenticated_session and not trusted:
                # Re-check weak negatives now that we can read authenticated pages.
                continue
            result.add(app_id)
        return result

    def _load_no_drop_cache(self) -> None:
        try:
            if not self.cache_path.exists():
                return
            with open(self.cache_path, encoding="utf-8") as f:
                raw = json.load(f)
            if not isinstance(raw, dict):
                return
            for steam_key, games in raw.items():
                if not isinstance(games, dict):
                    continue
                bucket: dict[int, dict[str, Any]] = {}
                for app_id_str, meta in games.items():
                    try:
                        app_id = int(app_id_str)
                    except (TypeError, ValueError):
                        continue
                    if not isinstance(meta, dict):
                        continue
                    bucket[app_id] = {
                        "ts": float(meta.get("ts", 0) or 0),
                        "trusted": bool(meta.get("trusted")),
                    }
                if bucket:
                    self._no_drop_cache[str(steam_key)] = bucket
        except Exception as e:  # noqa: BLE001 - cache is best-effort
            logger.debug("Failed to load no-drop cache: %s", e)

    def _save_no_drop_cache(self) -> None:
        if not self.cache_enabled or not self._no_drop_dirty:
            return
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            out: dict[str, dict[str, dict[str, Any]]] = {}
            for steam_key, games in self._no_drop_cache.items():
                out[steam_key] = {str(app_id): meta for app_id, meta in games.items()}
            with open(self.cache_path, "w", encoding="utf-8") as f:
                json.dump(out, f)
            self._no_drop_dirty = False
        except Exception as e:  # noqa: BLE001 - cache is best-effort
            logger.debug("Failed to save no-drop cache: %s", e)
