"""Load authenticated steamcommunity cookies from a locally logged-in browser.

__all__ = ["is_community_token", "load_community_cookies"]

The bot's card-drop scraping needs a `steamLoginSecure` cookie whose JWT audience
is `web:community`. Browser-exported "store" cookies (`web:store`) silently fail on
community pages. When the configured session is not authenticated, we can recover a
valid session from a browser the user is logged into Steam with — keeping the bot
self-healing as those short-lived community tokens rotate.
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Cookies needed to authenticate steamcommunity web requests.
_WANTED_COOKIES = ("steamLoginSecure", "sessionid", "steamCountry", "browserid", "timezoneOffset")


def _decode_jwt_payload(token_value: str) -> dict[str, Any] | None:
    """Decode the JWT payload embedded in a steamLoginSecure cookie value."""
    raw = token_value
    for sep in ("%7C%7C", "||"):
        if sep in raw:
            raw = raw.split(sep, 1)[1]
            break
    else:
        return None

    parts = raw.split(".")
    if len(parts) < 2:
        return None

    payload = parts[1]
    payload += "=" * (-len(payload) % 4)
    try:
        return json.loads(base64.urlsafe_b64decode(payload))
    except (ValueError, binascii.Error, json.JSONDecodeError):
        return None


def is_community_token(token_value: str, steam_id: str | None = None) -> bool:
    """Return True if the cookie is a community-audience token for the expected account."""
    payload = _decode_jwt_payload(token_value)
    if not payload:
        return False

    audience = payload.get("aud") or []
    if "web:community" not in audience:
        return False

    if steam_id:
        digits = "".join(ch for ch in str(steam_id) if ch.isdigit())
        if digits and payload.get("sub") not in (digits, str(steam_id)):
            return False

    return True


def load_community_cookies(steam_id: str | None = None, browser: str = "auto") -> dict[str, str] | None:
    """Return a dict of steamcommunity cookies from a local browser, or None.

    Args:
        steam_id: expected account, used to reject cookies for a different login.
        browser: "auto" (try every supported browser) or a specific browser name
            (chrome, firefox, edge, brave, chromium, opera, vivaldi, librewolf).
    """
    try:
        import browser_cookie3  # type: ignore[import-untyped]
    except ImportError:
        logger.debug("browser_cookie3 not installed; cannot recover cookies from the browser")
        return None

    loaders = {
        "chrome": getattr(browser_cookie3, "chrome", None),
        "firefox": getattr(browser_cookie3, "firefox", None),
        "edge": getattr(browser_cookie3, "edge", None),
        "brave": getattr(browser_cookie3, "brave", None),
        "chromium": getattr(browser_cookie3, "chromium", None),
        "opera": getattr(browser_cookie3, "opera", None),
        "vivaldi": getattr(browser_cookie3, "vivaldi", None),
        "librewolf": getattr(browser_cookie3, "librewolf", None),
    }

    if browser != "auto":
        loader = loaders.get(browser.lower())
        candidates = [loader] if loader else []
    else:
        candidates = [browser_cookie3.load, *[fn for fn in loaders.values() if fn]]

    for loader in candidates:
        try:
            jar = loader(domain_name="steamcommunity.com")
        except Exception as err:  # noqa: BLE001 - keyring/locked DB/etc.
            logger.debug("Cookie loader %s failed: %s", getattr(loader, "__name__", loader), err)
            continue

        cookies = {c.name: c.value for c in jar if c.name in _WANTED_COOKIES}
        token = cookies.get("steamLoginSecure")
        if token and is_community_token(token, steam_id):
            logger.debug("Loaded community cookies via %s", getattr(loader, "__name__", loader))
            return cookies

    return None
