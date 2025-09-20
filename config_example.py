"""Example configuration for the Steam idle bot.

Copy this file to config.py and replace the placeholders with your Steam
account details. Keep the populated config.py out of version control.
"""

USERNAME = "your_steam_username"
PASSWORD = "your_steam_password"

GAME_APP_IDS = [570, 730]

# Trading card filtering
FILTER_TRADING_CARDS = True  # Set to True to only idle games with trading cards
USE_OWNED_GAMES = True  # Set to True to automatically get games from your library
MAX_GAMES_TO_IDLE = 30  # Maximum number of games to idle simultaneously

# Steam Web API key (OPTIONAL but recommended)
# Get yours at: https://steamcommunity.com/dev/apikey
STEAM_API_KEY = None

# Logging level
LOG_LEVEL = "INFO"  # DEBUG, INFO, WARNING, ERROR
