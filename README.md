# Steam Idle Bot with Trading Card Support

![CI](https://github.com/bernardopg/steam-idler-python/actions/workflows/ci.yml/badge.svg)

## 🚀 Features

- ✅ **Trading Card Filtering**: Automatically detect and idle only games that have Steam Trading Cards
- ✅ **Automatic Game Library Detection**: Use your owned games instead of manually specifying them
- ✅ **Modern Configuration**: Type-safe configuration with Pydantic and environment variables
- ✅ **Steam Guard Support**: Handles Steam Guard authentication automatically
- ✅ **Robust Error Handling**: Custom exceptions and graceful handling of network errors
- ✅ **Structured Logging**: Rich console output with configurable log levels
- ✅ **Periodic Refresh**: Automatically refreshes game status and library
- ✅ **Modern Python Tooling**: Uses UV for fast dependency management
- ✅ **Modular Architecture**: Clean separation of concerns with maintainable code
- ✅ **Comprehensive Testing**: Unit tests with >80% coverage

## 📋 Requirements

- Python 3.9+
- Steam account with games
- Optional: Steam Web API key for better functionality

## 🛠️ Installation

### Using UV (Recommended)

1. **Install UV** (if not already installed):

   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

2. **Clone and setup**:

   ```bash
   git clone https://github.com/bernardopg/steam-idler-python.git
   cd steam-idler-python
   ```

3. **Install dependencies**:

   ```bash
   uv sync
   ```

4. **Configure the bot**:

   ```bash
   cp config_example.py config.py
   # Edit config.py with your Steam credentials
   ```

> Note: This project is UV-first. If you must use pip, mirror dependencies from `pyproject.toml` and proceed at your own risk.

## ⚙️ Configuration

### Method 1: Python config file (config.py)

```python
# Steam credentials (REQUIRED)
USERNAME = "your_steam_username"
PASSWORD = "your_steam_password"

# Game configuration
GAME_APP_IDS = [570, 730]  # Default games to idle
FILTER_TRADING_CARDS = True  # Only idle games with trading cards
USE_OWNED_GAMES = True  # Use your Steam library automatically
MAX_GAMES_TO_IDLE = 30  # Max games to idle simultaneously

# Steam Web API key (OPTIONAL but recommended)
STEAM_API_KEY = "your_api_key"  # Get from https://steamcommunity.com/dev/apikey

# Logging
LOG_LEVEL = "INFO"  # DEBUG, INFO, WARNING, ERROR, CRITICAL
LOG_FILE = None  # Optional log file path

# Performance
API_TIMEOUT = 10  # API request timeout in seconds
RATE_LIMIT_DELAY = 0.5  # Delay between API calls
```

### Method 2: Environment variables

```bash
export STEAM_USERNAME="your_steam_username"
export STEAM_PASSWORD="your_steam_password"
export STEAM_API_KEY="your_api_key"
```

### Method 3: .env file

Create a `.env` file:

```text
STEAM_USERNAME=your_steam_username
STEAM_PASSWORD=your_steam_password
STEAM_API_KEY=your_api_key
```

## 🎯 Usage

### Quick Start

```bash
# Test configuration (dry run)
./run.sh --dry-run

# Run normally
./run.sh

# Run with custom options
./run.sh --no-trading-cards --max-games 10

# Alternatively, via module directly
uv run python -m steam_idle_bot --dry-run
```

### Command Line Options

```bash
--dry-run              # Test configuration without connecting to Steam
--no-trading-cards     # Skip trading card filtering for faster startup
--max-games N          # Override MAX_GAMES_TO_IDLE configuration
--config PATH          # Use custom configuration file
--no-cache             # Disable persistent trading-card cache
--max-checks N         # Cap number of store lookups (performance)
--skip-failures        # Suppress non-timeout error logs during checks
```

### Examples

```bash
# Basic usage
./run.sh

# Skip trading card detection
./run.sh --no-trading-cards

# Limit to 5 games
./run.sh --max-games 5

# Test configuration
./run.sh --dry-run

# Use environment variables
STEAM_USERNAME=myuser STEAM_PASSWORD=mypass ./run.sh
```

## 🔄 How Trading Card Detection Works

The bot uses the Steam Store API to check if games have trading cards:

1. Queries `https://store.steampowered.com/api/appdetails`
2. Checks for category ID 29 (Steam Trading Cards)
3. Uses a persistent JSON cache with TTL to avoid repeated API calls
4. Uses an HTTP session with retries/backoff for resilience
5. Respects rate limits with configurable delays

## 🛡️ Security Notes

- **Never commit config.py** - it contains your Steam credentials
- Use environment variables for CI/CD
- Consider using a dedicated Steam account for idling
- The bot uses the same authentication as the official Steam client
- All credentials are validated to prevent placeholder values

## 🧪 Development

### Project Structure

```text
steam-idle-bitter/
├── src/
│   └── steam_idle_bot/
│       ├── __init__.py
│       ├── main.py              # Main entry point
│       ├── config/
│       │   ├── __init__.py
│       │   └── settings.py      # Configuration management
│       ├── steam/
│       │   ├── __init__.py
│       │   ├── client.py        # Steam client wrapper
│       │   ├── games.py         # Game library management
│       │   └── trading_cards.py # Trading card detection
│       └── utils/
│           ├── __init__.py
│           ├── logger.py        # Logging configuration
│           └── exceptions.py    # Custom exceptions
├── tests/
│   ├── unit/
│   │   ├── test_settings.py
│   │   └── test_trading_cards.py
│   └── integration/
├── docs/
├── scripts/
├── configs/
├── idle_bot.py (legacy)
├── run.sh
└── README.md
```

### Running Tests

```bash
# With UV
uv run pytest tests/ -v

# With coverage
uv run pytest tests/ --cov=steam_idle_bot --cov-report=html

# Run specific test file
uv run pytest tests/unit/test_settings.py -v
```

### Development Setup

```bash
# Install development dependencies
uv sync --dev

# Run linting
uv run ruff check src/
uv run ruff format src/

# Type checking
uv run mypy src/
```

## 🐛 Troubleshooting

### Common Issues

### "Steam credentials not configured"

- Ensure config.py exists and has real credentials
- Check for placeholder values like "your_steam_username"

### "ImportError: No module named 'steam'"

- Run `uv sync` to install dependencies
- Ensure Python 3.9+ is being used

### "Login failed"

- Check Steam Guard mobile app for 2FA code
- Verify username and password are correct
- Ensure Steam account is not locked

### "No games found to idle"

- Check if you have games with trading cards
- Verify Steam API key is set for library access
- Try with `--no-trading-cards` flag

### Debug Mode

```bash
# Enable debug logging
LOG_LEVEL=DEBUG ./run.sh

# Or in config.py
LOG_LEVEL = "DEBUG"
```

## 📊 Monitoring

The bot provides detailed logging:

- **INFO**: General operation status
- **WARNING**: Non-critical issues
- **ERROR**: Critical problems
- **DEBUG**: Detailed debugging information

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Add tests for new functionality
4. Ensure all tests pass
5. Submit a pull request

## 📄 License

This project is for educational purposes. Use responsibly and in accordance with Steam's Terms of Service.

## 🆘 Support

- Check the [Issues](https://github.com/bernardopg/steam-idler-python/issues) page
- Review the troubleshooting section
- Enable debug logging for detailed information
