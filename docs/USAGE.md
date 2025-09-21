# Usage Guide

This guide summarizes how to run Steam Idle Bot, the available CLI flags, and a few practical examples. For a deeper overview, see the README’s sections on installation, configuration, and troubleshooting.

## Quick start

```bash
# Dry run (no network, prints configuration and selected games)
./run.sh --dry-run

# Normal run
./run.sh

# Alternatively, run via the module entry
uv run python -m steam_idle_bot --dry-run
```

## Command line flags

```bash
--dry-run              # Test configuration without connecting to Steam
--no-trading-cards     # Skip trading-card filtering for faster startup
--max-games N          # Override configured max games to idle
--config PATH          # Use a custom configuration file
--no-cache             # Disable persistent trading-card cache
--max-checks N         # Cap number of store lookups (performance)
--skip-failures        # Suppress non-timeout error logs during checks
```

## Examples

```bash
# Skip trading-card detection and just pick the first 10 games
./run.sh --no-trading-cards --max-games 10

# Use caching but reduce external calls for a big library
./run.sh --max-checks 50 --skip-failures

# Provide credentials via environment variables for a one-off run
STEAM_USERNAME=myuser STEAM_PASSWORD=mypass ./run.sh --dry-run
```

## Configuration tips

- Preferred: copy `config_example.py` to `config.py` and fill in your credentials.
- Environment variables are supported: `STEAM_USERNAME`, `STEAM_PASSWORD`, and optional `STEAM_API_KEY`.
- A `.env` file is also supported (see README for details).

## Where to go next

- Installation and setup: see the README Installation section
- Full flag list and detection details: see the README Command Line Options and How Trading Card Detection Works
- Troubleshooting: consult the README Troubleshooting section
