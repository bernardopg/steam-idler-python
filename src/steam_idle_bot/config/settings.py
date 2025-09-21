"""Configuration management using Pydantic v2 for type safety and validation."""

from pathlib import Path
from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings with validation and environment variable support."""

    # Steam credentials
    username: str = Field(..., description="Steam username")
    password: str = Field(..., description="Steam password")

    # Game configuration
    game_app_ids: list[int] = Field(
        default=[570, 730],
        description="Default game IDs to idle when not using owned games",
    )
    filter_trading_cards: bool = Field(
        default=True, description="Only idle games that have Steam trading cards"
    )
    use_owned_games: bool = Field(
        default=True, description="Automatically use games from Steam library"
    )
    max_games_to_idle: int = Field(
        default=30,
        ge=1,
        le=32,
        description="Maximum number of games to idle simultaneously (Steam limit: 32)",
    )

    # Steam API
    steam_api_key: Optional[str] = Field(
        default=None,
        description="Steam Web API key for better functionality",
    )

    # Logging
    log_level: str = Field(
        default="INFO",
        pattern=r"^(DEBUG|INFO|WARNING|ERROR|CRITICAL)$",
        description="Logging level",
    )
    log_file: Optional[str] = Field(default=None, description="Optional log file path")

    # Performance
    api_timeout: int = Field(
        default=10, ge=1, le=60, description="Timeout for API requests in seconds"
    )
    rate_limit_delay: float = Field(
        default=0.5,
        ge=0.1,
        le=5.0,
        description="Delay between API calls to respect rate limits",
    )

    # Trading-card cache
    enable_card_cache: bool = Field(
        default=True,
        description="Enable persistent cache for trading card checks",
    )
    card_cache_path: str = Field(
        default=".cache/trading_cards.json",
        description="Path to JSON cache for trading card results",
    )
    card_cache_ttl_days: int = Field(
        default=30,
        ge=1,
        le=365,
        description="TTL for trading card cache entries (days)",
    )

    # Filtering controls
    max_checks: Optional[int] = Field(
        default=None,
        ge=1,
        le=10000,
        description="Optional cap on number of trading-card checks (performance)",
    )
    skip_failures: bool = Field(
        default=False,
        description="Skip logging non-timeout errors during trading-card checks",
    )

    # Security
    enable_encryption: bool = Field(
        default=False, description="Enable encryption for stored credentials"
    )

    @field_validator("username", "password")
    @classmethod
    def validate_credentials(cls, v: str, info):
        """Validate that credentials are not placeholders."""
        if isinstance(v, str):
            v = v.strip()
            if v.lower() in {"", "your_steam_username", "your_steam_password"}:
                field_name = getattr(info, "field_name", "credential")
                raise ValueError(
                    f"Invalid {field_name}: please provide real credentials, "
                    f"not placeholder values from config_example.py"
                )
        return v

    @field_validator("game_app_ids", mode="before")
    @classmethod
    def validate_game_ids(cls, v):
        """Validate game IDs are positive integers."""
        try:
            iterable = list(v)
        except Exception:
            raise ValueError("All game IDs must be positive integers") from None

        for game_id in iterable:
            if not isinstance(game_id, int) or game_id <= 0:
                raise ValueError("All game IDs must be positive integers")
        return v

    # Pydantic v2 settings config
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        validate_default=True,
        populate_by_name=True,
    )

    @classmethod
    def load_from_file(cls, config_path: Optional[Path] = None) -> "Settings":
        """Load settings from configuration file."""
        if config_path is None:
            config_path = Path("config.py")

        if config_path.exists():
            # Import and convert legacy config.py
            import importlib.util

            spec = importlib.util.spec_from_file_location("config", config_path)
            if spec and spec.loader:
                config_module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(config_module)

                # Map legacy config to new settings
                legacy_mapping = {
                    "USERNAME": "username",
                    "PASSWORD": "password",
                    "GAME_APP_IDS": "game_app_ids",
                    "FILTER_TRADING_CARDS": "filter_trading_cards",
                    "USE_OWNED_GAMES": "use_owned_games",
                    "MAX_GAMES_TO_IDLE": "max_games_to_idle",
                    "STEAM_API_KEY": "steam_api_key",
                    "LOG_LEVEL": "log_level",
                }

                kwargs = {}
                for legacy_key, new_key in legacy_mapping.items():
                    if hasattr(config_module, legacy_key):
                        kwargs[new_key] = getattr(config_module, legacy_key)

                return cls(**kwargs)

        # Try to load from environment variables explicitly to avoid constructing
        # the model without required credentials.
        import os

        env_username = os.getenv("USERNAME") or os.getenv("STEAM_USERNAME")
        env_password = os.getenv("PASSWORD") or os.getenv("STEAM_PASSWORD")
        if env_username and env_password:
            return cls(username=env_username, password=env_password)

        raise ValueError(
            "Missing credentials: provide config.py or set USERNAME and PASSWORD in the environment"
        )
