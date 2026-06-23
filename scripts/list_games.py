"""Ad-hoc: list all owned games, then all games with trading cards. Prints full output."""

from __future__ import annotations

import sys

import requests

from steam_idle_bot.config.settings import Settings
from steam_idle_bot.steam.steam_utility import SteamUtilityBridge
from steam_idle_bot.steam.trading_cards import TradingCardDetector


def resolve_steam_id(settings: Settings) -> str:
    report = SteamUtilityBridge(settings.steam_utility_path).get_state_report()
    sid = report.get("activeSteamId") or report.get("ActiveSteamId")
    if not sid:
        raise SystemExit("could not resolve steam_id from steam-utility state-report")
    return str(sid)


def fetch_owned_with_names(settings: Settings, steam_id: str) -> dict[int, str]:
    url = "https://api.steampowered.com/IPlayerService/GetOwnedGames/v1/"
    params = {
        "key": settings.steam_api_key,
        "steamid": steam_id,
        "format": "json",
        "include_appinfo": 1,
        "include_played_free_games": 1,
    }
    resp = requests.get(url, params=params, timeout=settings.api_timeout, headers={"User-Agent": "Steam-Idle-Bot/1.0"})
    resp.raise_for_status()
    games = resp.json().get("response", {}).get("games", [])
    return {int(g["appid"]): str(g.get("name", f"App {g['appid']}")) for g in games}


def main() -> None:
    settings = Settings.load_from_file()
    steam_id = resolve_steam_id(settings)
    print(f"Steam ID: {steam_id}")
    print(f"API key set: {bool(settings.steam_api_key)}")
    print("=" * 70)

    names = fetch_owned_with_names(settings, steam_id)
    all_ids = sorted(names)
    print(f"\n### ALL OWNED GAMES ({len(all_ids)}) ###\n")
    for app_id in all_ids:
        print(f"{app_id:>10}  {names[app_id]}")

    print("\n" + "=" * 70)
    print(f"\nChecking trading cards for {len(all_ids)} games (store API, cached, adaptive throttle)...")
    sys.stdout.flush()

    detector = TradingCardDetector(
        timeout=settings.api_timeout,
        rate_limit_delay=settings.rate_limit_delay,
        cache_enabled=True,
        cache_path=settings.card_cache_path,
        cache_ttl_days=settings.card_cache_ttl_days,
        session=TradingCardDetector.build_session(),
    )

    with_cards = detector.filter_games_with_trading_cards(all_ids, max_games=len(all_ids))
    with_cards_sorted = sorted(with_cards)

    print(f"\n### GAMES WITH TRADING CARDS ({len(with_cards_sorted)} / {len(all_ids)}) ###\n")
    for app_id in with_cards_sorted:
        print(f"{app_id:>10}  {names.get(app_id, f'App {app_id}')}")

    stats = detector.get_cache_stats()
    print("\n" + "=" * 70)
    print(f"Cache: {stats}")
    print(f"Summary: {len(all_ids)} owned | {len(with_cards_sorted)} with cards")


if __name__ == "__main__":
    main()
