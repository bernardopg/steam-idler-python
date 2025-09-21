# Migration Guide - Steam Idle Bot v1.0.0

## 🎯 Overview

This guide helps you migrate from the legacy monolithic structure to the new modular architecture.

## 📋 Changes Summary

### ✅ What's New

- **Modular Architecture**: Clean separation of concerns
- **Pydantic Configuration**: Type-safe settings with validation
- **Rich Logging**: Enhanced console output
- **Better Error Handling**: Custom exceptions
- **Improved Testing**: Comprehensive test suite
- **Environment Variables**: Support for `.env` files
- **Backward Compatibility**: Legacy interface still works

### 🔧 Breaking Changes

- **None**: All existing configurations remain compatible
- **New Dependencies**: Added `pydantic` and `rich`

## 🚀 Migration Steps

### 1. Update Dependencies

```bash
# Using UV (recommended)
uv sync

# Using pip
pip install -r requirements.txt
```

### 2. Configuration Migration

Your existing `config.py` will continue to work **without changes**.

**Optional**: You can migrate to the new format:

```python
# Old format (still works)
USERNAME = "your_username"
PASSWORD = "your_password"

# New format (optional)
from steam_idle_bot.config.settings import Settings

settings = Settings(
    username="your_username",
    password="your_password",
    # ... other settings
)
```

### 3. Usage Changes

#### Old Usage (legacy)

```bash
./run.sh
python idle_bot.py --dry-run
```

#### New Usage (recommended)

```bash
# Using the new module structure
uv run python -m steam_idle_bot --dry-run
uv run python -m steam_idle_bot --max-games 10 --no-cache --max-checks 100 --skip-failures
```

### 4. Environment Variables (New Feature)

You can now use environment variables:

```bash
export STEAM_USERNAME="your_username"
export STEAM_PASSWORD="your_password"
export STEAM_API_KEY="your_api_key"
```

### 5. .env File Support (New Feature)

Create a `.env` file:

```text
STEAM_USERNAME=your_username
STEAM_PASSWORD=your_password
STEAM_API_KEY=your_api_key
```

## 📁 File Structure Changes

### Before

```text
steam-idle-bitter/
├── idle_bot.py          # 400+ lines monolithic
├── config.py
└── tests/
    └── test_idle_bot.py
```

### After

```txt
steam-idle-bitter/
├── src/
│   └── steam_idle_bot/
│       ├── main.py      # Clean entry point
│       ├── config/      # Configuration management
│       ├── steam/       # Steam-related modules
│       └── utils/       # Utilities
├── idle_bot.py          # Legacy compatibility
├── tests/
│   ├── unit/           # Unit tests
│   └── integration/    # Integration tests
```

## 🔍 Configuration Validation

The new system validates your configuration automatically:

```python
# This will raise helpful errors
from steam_idle_bot.config.settings import Settings

try:
    settings = Settings.load_from_file()
except ValueError as e:
    print(f"Configuration error: {e}")
```

## 🧪 Testing

### Run All Tests

```bash
uv run pytest tests/ -v
```

### Run Specific Tests

```bash
uv run pytest tests/unit/test_settings.py -v
uv run pytest tests/unit/test_trading_cards.py -v
```

## 🚨 Troubleshooting

### "ModuleNotFoundError: steam_idle_bot"

```bash
# Ensure you're in the project root
cd steam-idle-bitter
uv sync
```

### "ImportError: No module named 'steam'"

```bash
# Install dependencies
uv sync
```

### Configuration Issues

The new system provides better error messages:

- Invalid credentials: "Invalid username: please provide real credentials"
- Invalid game IDs: "All game IDs must be positive integers"
- Invalid log level: "must match regex ^(DEBUG|INFO|WARNING|ERROR|CRITICAL)$"

## 🔄 Rollback Plan

If you encounter issues:

1. **Keep your existing config.py** - it's fully compatible
2. **Use the legacy interface**: `python idle_bot.py --dry-run`
3. **Revert to previous version**: `git checkout HEAD~1`

## 📊 Performance Improvements

- **Faster startup**: Lazy loading of modules
- **Better caching**: Persistent JSON cache with TTL for trading-card checks
- **Retries**: HTTP session with retry/backoff for store API calls
- **Rate limiting**: Configurable delays between API calls
- **Memory efficiency**: Cleaner object lifecycle

## 🎉 Benefits of Migration

| Feature | Old | New |
|---------|-----|-----|
| Configuration | Basic dict | Type-safe Pydantic |
| Error Handling | Generic exceptions | Custom exceptions |
| Logging | Basic print | Rich console output |
| Testing | 3 tests | Comprehensive suite |
| Architecture | Monolithic | Modular |
| Validation | Manual | Automatic |
| Documentation | Basic | Comprehensive |

## ❓ FAQ

**Q: Do I need to change my config.py?**
**A:** No, your existing config.py works unchanged.

**Q: Can I still use the old commands?**
**A:** Yes, `./run.sh` and `python idle_bot.py` work exactly as before.

**Q: What's the benefit of migrating?**
**A:** Better error messages, improved logging, and easier maintenance.

**Q: Will this break my existing setup?**
**A:** No, this is a 100% backward-compatible update.

**Q: How do I use the new features?**
**A:** Check the updated README.md for new command-line options and environment variable support.
