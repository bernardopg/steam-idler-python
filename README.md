# Steam Idle Bot with Trading Card Support

## Features

- ✅ **Trading Card Filtering**: Automatically detect and idle only games that have Steam Trading Cards
- ✅ **Automatic Game Library Detection**: Use your owned games instead of manually specifying them
- ✅ **Configurable Settings**: Easy configuration through config file
- ✅ **Steam Guard Support**: Handles Steam Guard authentication automatically
- ✅ **Robust Error Handling**: Graceful handling of network errors and API issues
- ✅ **Periodic Refresh**: Automatically refreshes game status and library

## Installation

**Note**: This bot requires Python 3.9-3.11. Python 3.12+ has compatibility issues with the steam library.

1. **Create a virtual environment with Python 3.11**:

   ```bash
   # Using pyenv (recommended)
   pyenv install 3.11.0
   pyenv virtualenv 3.11.0 steam-idle
   pyenv activate steam-idle

   # OR using conda
   conda create -n steam-idle python=3.11
   conda activate steam-idle

   # OR using system Python 3.11
   python3.11 -m venv .venv
   source .venv/bin/activate
   ```

2. **Install Python dependencies**:

   ```bash
   pip install -r requirements.txt
   ```

   Required packages:
   - requests: For making HTTP requests to the Steam API
   - steam: Python library for interacting with the Steam client

3. **Copy the example configuration**:

   ```bash
   cp config_example.py config.py
   ```

4. **Edit `config.py` with your Steam credentials and preferences**

## Configuration

Edit `config.py` to customize the bot behavior:

```python
# Steam credentials (REQUIRED)
USERNAME = "your_steam_username"
PASSWORD = "your_steam_password"

# Trading card filtering
FILTER_TRADING_CARDS = True    # Only idle games with trading cards
USE_OWNED_GAMES = True         # Use your game library automatically
MAX_GAMES_TO_IDLE = 30         # Max games to idle simultaneously

# Optional Steam Web API key for better functionality
STEAM_API_KEY = "your_api_key"  # Get from https://steamcommunity.com/dev/apikey
```

### Configuration Options

- **FILTER_TRADING_CARDS**: When `True`, only games with trading cards will be idled
- **USE_OWNED_GAMES**: When `True`, automatically fetches games from your Steam library
- **MAX_GAMES_TO_IDLE**: Limits the number of games idled simultaneously (Steam limit is ~32)
- **STEAM_API_KEY**: Optional API key for better game library access (recommended)

## Usage

Simply run the bot:

```bash
python idle_bot.py
```

The bot will:

1. Connect to Steam using your credentials
2. Handle Steam Guard authentication if needed
3. Fetch your game library (if USE_OWNED_GAMES is True)
4. Filter games with trading cards (if FILTER_TRADING_CARDS is True)
5. Start idling the selected games
6. Refresh the game status every 10 minutes

## How Trading Card Detection Works

The bot checks each game by querying the Steam Store API to see if it has the "Steam Trading Cards" category (category ID 29). This ensures you're only idling games that can actually drop trading cards.

## Security Notes

- **Never share your config.py file** - it contains your Steam credentials
- Consider using a Steam API key for better reliability
- The bot uses the same authentication as the official Steam client

## Default Game IDs

If you prefer to manually specify games, here are some popular ones with trading cards:

- 570 - Dota 2
- 730 - Counter-Strike: Global Offensive
- 440 - Team Fortress 2
- 753 - Steam (has trading cards)
- 304930 - Unturned

## License

This project is for educational purposes. Use responsibly and in accordance with Steam's Terms of Service.
# steam-idler-python
