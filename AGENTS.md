# Repository Guidelines

## Project Structure & Module Organization

The bot lives in `idle_bot.py`, which orchestrates Steam authentication, game discovery, and idling. Check `config_example.py` into version control and copy it to a local `config.py` for secrets; never push populated credentials. Python dependencies are tracked in `pyproject.toml` using UV. No dedicated `tests/` directory exists yet—new suites should live there. Temporary run artifacts should stay confined to local virtualenv folders such as `.venv/`.

## Build, Test, and Development Commands

Use **UV** for all dependency management and execution:

### **UV Setup (Recommended)**

```bash
# Install UV if not already installed
curl -LsSf https://astral.sh/uv/install.sh | sh

# Clone and setup
git clone https://github.com/bernardopg/steam-idler-python.git
cd steam-idler-python

# Install dependencies
uv sync

# Copy config template
cp config_example.py config.py
```

### **Development Commands**

```bash
# Run the bot (module entry recommended)
uv run python -m steam_idle_bot --dry-run

# Run with custom options
uv run python -m steam_idle_bot --no-trading-cards --max-games 10 --no-cache --max-checks 50 --skip-failures

# Using the convenience script
./run.sh --dry-run

# Run tests
uv run pytest

# Lint code
uv run ruff check .

# Bytecode compile check
uv run python -m compileall src/steam_idle_bot
```

### **Legacy pip usage (deprecated)**

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Coding Style & Naming Conventions

Follow PEP 8 with 4-space indentation and `snake_case` identifiers. Keep functions small and focused on a single responsibility; prefer extracting helpers over nested control flow. Use type hints for public-facing functions (see `List[int]` annotations in `idle_bot.py`) and favor Python's `logging` module over print statements so log levels remain configurable from `config.py`.

## Testing Guidelines

Add new tests with `pytest` under `tests/` and mirror the module path (e.g., `tests/test_idle_bot.py`). Name tests after the behavior under scrutiny, such as `test_filter_games_with_trading_cards_handles_timeouts`. Mock network calls to the Steam APIs to keep runs deterministic. Aim for coverage on trading-card filtering, owned-game retrieval fallbacks, and authentication edge cases.

## UV-Specific Guidelines

- **Dependencies**: Always use `uv add package-name` to add new dependencies
- **Lockfile**: Commit `uv.lock` to ensure reproducible builds
- **Python version**: Project requires Python 3.9+ (configured in pyproject.toml)
- **Virtual environments**: UV manages `.venv` automatically - no manual activation needed

## Commit & Pull Request Guidelines

Base commit messages on the `<type>: <short summary>` pattern already present (e.g., `docs: update README for UV setup`). Group related fixes into single commits and keep summaries under 72 characters. Pull requests should describe the scenario, list manual or automated validation steps, and call out any config changes or new secrets required. Include screenshots or logs when altering authentication flows.

## Security & Configuration Tips

Never commit populated `config.py`; provide redacted examples instead. Prefer environment variables or local secrets managers for sensitive values. Rotate Steam credentials used for testing and clean test accounts after demos. When touching HTTP requests, validate timeouts and error handling so the bot degrades safely under API instability.

## Troubleshooting

### **Protobuf Issues**

If you encounter protobuf version conflicts:

```bash
# UV will handle this automatically
uv sync
```

### **Steam Library Issues**

- Ensure Python 3.9+ is being used
- Check that protobuf==3.20.3 is installed (handled by UV)
- Verify Steam credentials in config.py

### **UV-specific Issues**

```bash
# Clear UV cache if needed
uv cache clean

# Reinstall dependencies
uv sync --reinstall
