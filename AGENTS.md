# Repository Guidelines

## Project Structure & Module Organization
The bot lives in `idle_bot.py`, which orchestrates Steam authentication, game discovery, and idling. Check `config_example.py` into version control and copy it to a local `config.py` for secrets; never push populated credentials. Python dependencies are tracked in `requirements.txt`. No dedicated `tests/` directory exists yet—new suites should live there. Temporary run artifacts should stay confined to local virtualenv folders such as `venv/`.

## Build, Test, and Development Commands
Use `python3.11 -m venv venv && source venv/bin/activate` to match the supported interpreter range. Install dependencies with `pip install -r requirements.txt`, then copy the sample config via `cp config_example.py config.py` and fill in your credentials. Run the bot locally with `python idle_bot.py` or add flags such as `python idle_bot.py --no-trading-cards --max-games 10` to accelerate filtering during development. Before submitting, execute `python -m compileall idle_bot.py` to catch syntax regressions until an automated test suite lands.

## Coding Style & Naming Conventions
Follow PEP 8 with 4-space indentation and `snake_case` identifiers. Keep functions small and focused on a single responsibility; prefer extracting helpers over nested control flow. Use type hints for public-facing functions (see `List[int]` annotations in `idle_bot.py`) and favor Python's `logging` module over print statements so log levels remain configurable from `config.py`.

## Testing Guidelines
Add new tests with `pytest` under `tests/` and mirror the module path (e.g., `tests/test_idle_bot.py`). Name tests after the behavior under scrutiny, such as `test_filter_games_with_trading_cards_handles_timeouts`. Mock network calls to the Steam APIs to keep runs deterministic. Aim for coverage on trading-card filtering, owned-game retrieval fallbacks, and authentication edge cases.

## Commit & Pull Request Guidelines
Base commit messages on the `<type>: <short summary>` pattern already present (e.g., `docs: update README for setup`). Group related fixes into single commits and keep summaries under 72 characters. Pull requests should describe the scenario, list manual or automated validation steps, and call out any config changes or new secrets required. Include screenshots or logs when altering authentication flows.

## Security & Configuration Tips
Never commit populated `config.py`; provide redacted examples instead. Prefer environment variables or local secrets managers for sensitive values. Rotate Steam credentials used for testing and clean test accounts after demos. When touching HTTP requests, validate timeouts and error handling so the bot degrades safely under API instability.
