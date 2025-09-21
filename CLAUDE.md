# Claude/Cline Development Guide - Steam Idle Bot

## Project Overview

Steam Idle Bot with Trading Card Support - migrated to UV for modern Python dependency management.

## Quick Start for Claude/Cline

### **Environment Setup**

```bash
# Install UV (if not available)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Project is already UV-ready
uv sync
```

### **Key Commands**

```bash
# Test the bot
uv run python idle_bot.py --dry-run

# Run normally
./run.sh

# Run tests
uv run pytest

# Lint code
uv run ruff check .

# Add dependencies
uv add package-name
```

### **Project Structure**

```text
steam-idle-bitter/
├── idle_bot.py          # Main bot script
├── pyproject.toml       # UV dependencies (modern)
├── config_example.py    # Template for config.py
├── run.sh              # Convenience script
├── tests/              # Test suite
├── .gitignore          # Git ignore rules
├── ruff.toml           # Linting configuration
└── README.md           # Updated documentation
```

### **Configuration**

- **config.py**: Contains Steam credentials (never commit)
- **config_example.py**: Template for new users
- **pyproject.toml**: All dependencies managed by UV

### **Dependencies (UV-managed)**

- **protobuf==3.20.3**: Fixed version for Steam compatibility
- **steam==1.4.4**: Steam client library
- **requests==2.32.4**: HTTP client
- **gevent==25.5.1**: Async networking

### **Common Tasks**

#### **Fixing Protobuf Issues**

The project uses protobuf 3.20.3 to avoid Steam library conflicts. UV handles this automatically.

#### **Adding New Dependencies**

```bash
uv add new-package-name
```

#### **Running Tests**

```bash
uv run pytest tests/
```

#### **Development Workflow**

1. Make changes to code
2. Test with: `uv run python idle_bot.py --dry-run`
3. Run tests: `uv run pytest`
4. Lint: `uv run ruff check .`
5. Commit changes

### **Important Notes**

- **Python 3.9+ required** (configured in pyproject.toml)
- **UV manages .venv automatically** - no manual activation needed
- **config.py is gitignored** - never commit credentials
- **Protobuf version is locked** to 3.20.3 for Steam compatibility

### **Troubleshooting**

- **UV cache issues**: `uv cache clean`
- **Dependency conflicts**: `uv sync --reinstall`
- **Python version**: Ensure 3.9+ is available

### **Legacy Support**

For pip-based setup (deprecated):

- Old requirements.txt has been removed
- Use `uv pip install -r requirements.txt` if needed for compatibility
