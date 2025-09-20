import argparse
import logging
import sys
import time

import requests
from steam.client import SteamClient

# Log the Python version and steam library version
logging.info(f"Python version: {sys.version}")
try:
    import steam

    logging.info(f"Steam library version: {steam.__version__}")
except (ImportError, AttributeError):
    logging.warning("Could not determine Steam library version")

# Try to import configuration from config.py, fallback to defaults
try:
    import config

    USERNAME = config.USERNAME
    PASSWORD = config.PASSWORD
    GAME_APP_IDS = getattr(config, "GAME_APP_IDS", [570, 730])
    FILTER_TRADING_CARDS = getattr(config, "FILTER_TRADING_CARDS", True)
    USE_OWNED_GAMES = getattr(config, "USE_OWNED_GAMES", True)
    MAX_GAMES_TO_IDLE = getattr(config, "MAX_GAMES_TO_IDLE", 30)
    STEAM_API_KEY = getattr(config, "STEAM_API_KEY", None)
    LOG_LEVEL = getattr(config, "LOG_LEVEL", "INFO")
except ImportError:
    logging.warning(
        "config.py not found. Copy config_example.py and provide credentials before running."
    )
    USERNAME = ""
    PASSWORD = ""
    GAME_APP_IDS = [570, 730]  # Default games to idle (Dota 2, CS:GO)
    FILTER_TRADING_CARDS = True  # Set to True to only idle games with trading cards
    USE_OWNED_GAMES = True  # Set to True to automatically get games from library
    MAX_GAMES_TO_IDLE = 30  # Maximum number of games to idle simultaneously
    STEAM_API_KEY = None  # Optional: Set your Steam API key for better functionality
    LOG_LEVEL = "INFO"

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(message)s",
    level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
)

client = None


def ensure_credentials_configured():
    """Abort early if credentials are missing or placeholders are used.

    We consider the example placeholders from config_example.py invalid to prevent
    accidental runs without real credentials.
    """
    placeholder_user = str(USERNAME).strip().lower() in {"", "your_steam_username"}
    placeholder_pass = str(PASSWORD).strip().lower() in {"", "your_steam_password"}
    if placeholder_user or placeholder_pass:
        logging.error(
            "Steam credentials not configured. Copy config_example.py to config.py "
            "and set USERNAME/PASSWORD before running."
        )
        sys.exit(1)


def initialize_client():
    """Initialize the Steam client with minimal setup to test compatibility."""
    global client
    try:
        client = SteamClient()
        return True
    except Exception as e:
        logging.error(f"Failed to initialize Steam client: {e}")
        return False


def main_loop():
    games_to_idle = None
    try:
        # We're already idling games from the login step, but we'll refresh periodically
        while True:
            time.sleep(10 * 60)  # every 10 minutes
            logging.info("Refreshing play status...")

            # Refresh games list periodically (every hour, 6 cycles)
            if games_to_idle is None or (time.time() % 3600 < 600):
                games_to_idle = get_games_to_idle()
                logging.info("Refreshed games list: %s", games_to_idle)

            if client and client.connected:
                # Use games_played method from the library
                if hasattr(client, "games_played"):
                    try:
                        client.games_played(games_to_idle)
                    except Exception as e:
                        logging.error(f"Error setting games played: {e}")
                else:
                    logging.error("Cannot set games played - method not found")
            else:
                logging.error("Client is not connected. Attempting to reconnect.")
                # We could add reconnection logic here if needed
    except KeyboardInterrupt:
        logging.info("Shutting down idle bot.")
        if client:
            # Use the available logout method
            if hasattr(client, "logout"):
                client.logout()
            elif hasattr(client, "disconnect"):
                client.disconnect()


def has_trading_cards(app_id: int) -> bool:
    """
    Check if a game has trading cards by querying the Steam store page.
    This is a simple check that looks for trading card information.
    """
    try:
        url = f"https://store.steampowered.com/api/appdetails?appids={app_id}&filters=categories"
        response = requests.get(url, timeout=5)  # Reduced timeout
        response.raise_for_status()  # Raise an exception for bad status codes
        data = response.json()

        if str(app_id) in data and data[str(app_id)]["success"]:
            categories = data[str(app_id)].get("data", {}).get("categories", [])
            # Category 29 is Steam Trading Cards
            return any(cat.get("id") == 29 for cat in categories)
        return False
    except KeyboardInterrupt:
        raise  # Re-raise KeyboardInterrupt so it can be handled upstream
    except requests.exceptions.RequestException as e:
        logging.warning(f"Network error checking trading cards for app {app_id}: {e}")
        return False
    except Exception as e:
        logging.warning(f"Could not check trading cards for app {app_id}: {e}")
        return False


def get_owned_games() -> list[int]:
    """
    Get the list of owned games from the user's Steam library.
    Note: This requires the user to be logged in and have a public profile
    or use Steam Web API.
    """
    try:
        # Get Steam ID - adaptado para considerar diferentes estruturas de cliente
        steam_id = None
        if client:
            if hasattr(client, "steam_id"):
                steam_id = client.steam_id
            elif (
                hasattr(client, "user")
                and client.user is not None
                and hasattr(client.user, "steam_id")
            ):
                steam_id = client.user.steam_id

        if STEAM_API_KEY and steam_id:
            # Use Steam Web API if available
            url = "http://api.steampowered.com/IPlayerService/GetOwnedGames/v0001/"
            params = {
                "key": STEAM_API_KEY,
                "steamid": steam_id,
                "format": "json",
                "include_appinfo": 1,
            }
            response = requests.get(url, params=params, timeout=10)
            data = response.json()

            if "response" in data and "games" in data["response"]:
                return [game["appid"] for game in data["response"]["games"]]

        # Fallback: use a property finder to find games in the client
        if client:
            # Try various possible attribute names for games
            for attr_name in ["games", "owned_games", "licenses"]:
                if hasattr(client, attr_name):
                    attr_value = getattr(client, attr_name)
                    if isinstance(attr_value, dict) and attr_value:
                        return list(attr_value.keys())

        logging.warning("Could not retrieve owned games, using default game list")
        return GAME_APP_IDS

    except Exception as e:
        logging.error(f"Error getting owned games: {e}")
        return GAME_APP_IDS


def filter_games_with_trading_cards(game_ids: list[int]) -> list[int]:
    """
    Filter a list of game IDs to only include games with trading cards.
    """
    if not FILTER_TRADING_CARDS:
        return game_ids

    logging.info("Filtering games with trading cards...")
    filtered_games = []

    try:
        for i, game_id in enumerate(game_ids):
            logging.info(f"Checking game {i + 1}/{len(game_ids)}: {game_id}")

            try:
                if has_trading_cards(game_id):
                    filtered_games.append(game_id)
                    logging.info(f"Game {game_id} has trading cards")
                else:
                    logging.debug(f"Game {game_id} does not have trading cards")
            except KeyboardInterrupt:
                logging.info("Interrupted by user. Using games found so far...")
                break
            except Exception as e:
                logging.warning(f"Error checking game {game_id}: {e}. Skipping...")
                continue

            # Add a small delay to avoid overwhelming the Steam API
            try:
                time.sleep(0.5)  # Slightly longer delay to be more respectful
            except KeyboardInterrupt:
                logging.info("Interrupted by user. Using games found so far...")
                break

    except KeyboardInterrupt:
        logging.info("Interrupted by user. Using games found so far...")

    logging.info(
        f"Trading-card games found: {len(filtered_games)} of {len(game_ids)} checked"
    )
    return (
        filtered_games[:MAX_GAMES_TO_IDLE]
        if filtered_games
        else game_ids[:MAX_GAMES_TO_IDLE]
    )


def get_games_to_idle() -> list[int]:
    """
    Get the final list of games to idle based on configuration.
    """
    if USE_OWNED_GAMES:
        logging.info("Getting owned games from Steam library...")
        games = get_owned_games()
        logging.info(f"Found {len(games)} owned games")
    else:
        logging.info("Using manually specified game list...")
        games = GAME_APP_IDS

    if FILTER_TRADING_CARDS:
        logging.info("Starting trading card filtering (this may take a while)...")
        logging.info(
            "Tip: Use --no-trading-cards flag to skip this step for faster startup"
        )
        games = filter_games_with_trading_cards(games)
    else:
        games = games[:MAX_GAMES_TO_IDLE]
        logging.info(f"Trading card filtering disabled, using first {len(games)} games")

    if not games:
        logging.warning("No games found to idle! Using default games.")
        return GAME_APP_IDS

    return games


if __name__ == "__main__":
    # Parse command line arguments
    parser = argparse.ArgumentParser(
        description="Steam Idle Bot with Trading Card Support"
    )
    parser.add_argument(
        "--no-trading-cards",
        action="store_true",
        help="Skip trading card filtering for faster startup",
    )
    parser.add_argument(
        "--max-games",
        type=int,
        default=MAX_GAMES_TO_IDLE,
        help=f"Maximum number of games to idle (default: {MAX_GAMES_TO_IDLE})",
    )
    args = parser.parse_args()

    # Override configuration based on command line args
    if args.no_trading_cards:
        FILTER_TRADING_CARDS = False
    if args.max_games:
        MAX_GAMES_TO_IDLE = args.max_games

    logging.info("Steam Idle Bot with Trading Card Support")
    logging.info("Configuration:")
    logging.info(f"  - Filter Trading Cards: {FILTER_TRADING_CARDS}")
    logging.info(f"  - Use Owned Games: {USE_OWNED_GAMES}")
    logging.info(f"  - Max Games to Idle: {MAX_GAMES_TO_IDLE}")
    logging.info(f"  - Steam API Key: {'Set' if STEAM_API_KEY else 'Not set'}")

    ensure_credentials_configured()

    logging.info("Initializing Steam client...")
    if not initialize_client():
        logging.error("Failed to initialize Steam client. Exiting.")
        exit(1)

    logging.info("Connecting to Steam…")
    if client:
        try:
            # Use the correct login method based on the available API
            if hasattr(client, "cli_login"):
                logging.info("Attempting login...")
                logging.info("Be ready to enter any authentication code if prompted.")
                result = client.cli_login(username=USERNAME, password=PASSWORD)
                logging.info("Login attempt completed, checking result...")
                if result == 1:
                    logging.info("Logged in successfully")

                    # Start idling after successful login
                    username = "Unknown"
                    if hasattr(client, "username"):
                        username = client.username
                    logging.info("Logged in as %s", username)

                    # Get the games to idle based on configuration
                    try:
                        games_to_idle = get_games_to_idle()
                    except KeyboardInterrupt:
                        logging.info(
                            "Game filtering interrupted by user. Using default games."
                        )
                        games_to_idle = GAME_APP_IDS[:MAX_GAMES_TO_IDLE]

                    # Use games_played method
                    if hasattr(client, "games_played"):
                        client.games_played(games_to_idle)
                        logging.info(
                            "Started idling %d games: %s",
                            len(games_to_idle),
                            games_to_idle,
                        )
                        if FILTER_TRADING_CARDS:
                            logging.info("Trading card filtering is ENABLED")
                        else:
                            logging.info("Trading card filtering is DISABLED")
                    else:
                        logging.error("No method available to set games played")

                    main_loop()
                else:
                    logging.error("Failed to log in with cli_login")
                    exit(1)
            # Try log_on method (newer versions)
            elif hasattr(client, "log_on"):
                client.log_on(username=USERNAME, password=PASSWORD)
                main_loop()
            # Fallback to login method (older versions)
            elif hasattr(client, "login"):
                client.login(USERNAME, PASSWORD)
                main_loop()
            else:
                logging.error("No login method available in Steam client. Exiting.")
                exit(1)
        except Exception as e:
            logging.error(f"Error during login: {e}")
            exit(1)
    else:
        logging.error("Client not initialized properly. Exiting.")
        exit(1)
