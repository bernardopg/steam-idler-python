"""Configuration management using Pydantic v2 for type safety and validation."""

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, ValidationError, field_validator
from pydantic_settings import (
    BaseSettings,
    DotEnvSettingsSource,
    EnvSettingsSource,
    SettingsConfigDict,
)

LIST_FIELDS = {"game_app_ids", "exclude_app_ids"}
COOKIE_MAP_FIELDS = {"steam_web_cookies"}


def _parse_int_list(value: Any) -> Any:
    """Parse comma-separated or JSON list values from environment strings."""
    if not isinstance(value, str):
        return value

    raw_value = value.strip()
    if raw_value == "":
        return []

    if raw_value.startswith("["):
        try:
            return json.loads(raw_value)
        except json.JSONDecodeError:
            return value

    parts = [part.strip() for part in raw_value.split(",") if part.strip()]
    if not parts:
        return []

    try:
        return [int(part) for part in parts]
    except ValueError:
        return value


def _parse_cookie_map(value: Any) -> Any:
    """Parse Steam cookie env values.

    Accepts:
    - JSON object: {"cookie": "value"}
    - JSON array export from browsers: [{"name":..., "value":..., "domain":...}, ...]
    - Semicolon list: "cookie=value; other=value"
    """
    if not isinstance(value, str):
        return value

    raw_value = value.strip()
    if raw_value == "":
        return {}

    if raw_value.startswith("{"):
        try:
            parsed = json.loads(raw_value)
        except json.JSONDecodeError:
            return value

        if isinstance(parsed, dict):
            return {str(key): str(cookie_value) for key, cookie_value in parsed.items()}
        return value

    if raw_value.startswith("["):
        try:
            parsed = json.loads(raw_value)
        except json.JSONDecodeError:
            return value

        if isinstance(parsed, list):
            normalized: list[dict[str, Any]] = []
            for item in parsed:
                if not isinstance(item, dict):
                    continue
                name = item.get("name")
                cookie_value = item.get("value")
                if not name or cookie_value is None:
                    continue
                normalized.append(
                    {
                        "name": str(name),
                        "value": str(cookie_value),
                        "domain": str(item.get("domain", "steamcommunity.com")),
                        "path": str(item.get("path", "/")),
                        "secure": bool(item.get("secure", False)),
                    }
                )

            return normalized

        return value

    cookies: dict[str, str] = {}
    for chunk in raw_value.replace("\n", ";").split(";"):
        part = chunk.strip()
        if not part:
            continue
        if "=" not in part:
            return value
        key, cookie_value = part.split("=", 1)
        key = key.strip()
        cookie_value = cookie_value.strip()
        if not key:
            return value
        cookies[key] = cookie_value

    return cookies if cookies else value


def _prepare_special_field_value(field_name: str, value: Any) -> tuple[bool, Any]:
    """Normalize selected fields read from env before model validation."""
    if field_name in LIST_FIELDS:
        return True, _parse_int_list(value)

    if field_name in COOKIE_MAP_FIELDS:
        return True, _parse_cookie_map(value)

    if field_name == "max_checks" and isinstance(value, str) and not value.strip():
        return True, None

    return False, value


class FlexibleEnvSettingsSource(EnvSettingsSource):
    """Environment source with tolerant parsing for list/int fields."""

    def prepare_field_value(self, field_name: str, field: Any, value: Any, value_is_complex: bool) -> Any:
        handled, parsed_value = _prepare_special_field_value(field_name, value)
        if handled:
            return parsed_value

        return super().prepare_field_value(field_name, field, value, value_is_complex)


class FlexibleDotEnvSettingsSource(DotEnvSettingsSource):
    """Dotenv source with tolerant parsing for list/int fields."""

    def prepare_field_value(self, field_name: str, field: Any, value: Any, value_is_complex: bool) -> Any:
        handled, parsed_value = _prepare_special_field_value(field_name, value)
        if handled:
            return parsed_value

        return super().prepare_field_value(field_name, field, value, value_is_complex)


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
    filter_trading_cards: bool = Field(default=True, description="Only idle games that have Steam trading cards")
    use_owned_games: bool = Field(default=True, description="Automatically use games from Steam library")
    filter_completed_card_drops: bool = Field(
        default=True,
        description="Skip games that have already dropped all available trading cards",
    )
    exclude_app_ids: list[int] = Field(default_factory=list, description="Always ignore these app IDs")
    max_games_to_idle: int = Field(
        default=30,
        ge=1,
        le=32,
        description="Maximum number of games to idle simultaneously (Steam limit: 32)",
    )
    idling_backend: Literal["python", "steam_utility"] = Field(
        default="python",
        description="Backend used to keep Steam games idling",
    )
    steam_utility_path: str | None = Field(
        default=None,
        description="Optional path to the local steam-utility-multiplataform repository",
    )

    # Steam API
    steam_api_key: str | None = Field(
        default=None,
        description="Steam Web API key for better functionality",
    )
    steam_web_cookies: Any = Field(
        default_factory=lambda: {},
        description="Steam browser cookies used to build an authenticated web session",
    )

    # Logging
    log_level: str = Field(
        default="INFO",
        pattern=r"^(DEBUG|INFO|WARNING|ERROR|CRITICAL)$",
        description="Logging level",
    )
    log_file: str | None = Field(default=None, description="Optional log file path")

    # Performance
    api_timeout: int = Field(default=10, ge=1, le=60, description="Timeout for API requests in seconds")
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
    max_checks: int | None = Field(
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
    enable_encryption: bool = Field(default=False, description="Enable encryption for stored credentials")

    @field_validator("username", "password")
    @classmethod
    def validate_credentials(cls, v: str, info):
        """Validate that credentials are not placeholders."""
        if isinstance(v, str):
            v = v.strip()
            if v.lower() in {"", "your_steam_username", "your_steam_password"}:
                field_name = getattr(info, "field_name", "credential")
                raise ValueError(f"Invalid {field_name}: please provide real credentials, not placeholder values from config_example.py")
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
        env_ignore_empty=True,
        validate_default=True,
        populate_by_name=True,
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls,
        init_settings,
        env_settings,
        dotenv_settings,
        file_secret_settings,
    ):
        """Customize source parsing to support common .env list/int formats."""
        source_kwargs = {
            "case_sensitive": settings_cls.model_config.get("case_sensitive"),
            "env_prefix": settings_cls.model_config.get("env_prefix"),
            "env_nested_delimiter": settings_cls.model_config.get("env_nested_delimiter"),
            "env_ignore_empty": settings_cls.model_config.get("env_ignore_empty"),
            "env_parse_none_str": settings_cls.model_config.get("env_parse_none_str"),
            "env_parse_enums": settings_cls.model_config.get("env_parse_enums"),
        }

        return (
            init_settings,
            FlexibleEnvSettingsSource(settings_cls, **source_kwargs),
            FlexibleDotEnvSettingsSource(
                settings_cls,
                env_file=settings_cls.model_config.get("env_file"),
                env_file_encoding=settings_cls.model_config.get("env_file_encoding"),
                **source_kwargs,
            ),
            file_secret_settings,
        )

    @classmethod
    def load_from_file(cls, config_path: Path | None = None) -> "Settings":
        """Load settings from configuration file."""
        explicit_config_path = config_path is not None
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
                    "FILTER_COMPLETED_CARD_DROPS": "filter_completed_card_drops",
                    "EXCLUDE_APP_IDS": "exclude_app_ids",
                    "USE_OWNED_GAMES": "use_owned_games",
                    "MAX_GAMES_TO_IDLE": "max_games_to_idle",
                    "IDLING_BACKEND": "idling_backend",
                    "STEAM_UTILITY_PATH": "steam_utility_path",
                    "STEAM_API_KEY": "steam_api_key",
                    "STEAM_WEB_COOKIES": "steam_web_cookies",
                    "LOG_LEVEL": "log_level",
                }

                kwargs = {}
                for legacy_key, new_key in legacy_mapping.items():
                    if hasattr(config_module, legacy_key):
                        kwargs[new_key] = getattr(config_module, legacy_key)

                return cls(**kwargs)
            if explicit_config_path:
                raise ValueError(
                    "Missing credentials: provide config.py or set USERNAME and PASSWORD in the environment"  # noqa: E501
                )
        elif explicit_config_path:
            raise ValueError(
                "Missing credentials: provide config.py or set USERNAME and PASSWORD in the environment"  # noqa: E501
            )

        try:
            settings_kwargs: dict[str, Any] = {}
            return cls(**settings_kwargs)
        except ValidationError as exc:
            missing_fields = {error.get("loc", (None,))[0] for error in exc.errors() if error.get("type") == "missing"}
            if "username" in missing_fields or "password" in missing_fields:
                raise ValueError(
                    "Missing credentials: provide config.py or set USERNAME and PASSWORD in the environment"  # noqa: E501
                ) from exc
            raise

    def save_to_env_file(self, path: Path | None = None) -> Path:
        """Persist the current settings to a dotenv file for future runs."""
        target = path or Path(".env")
        data = self.model_dump()

        env_mapping = {
            "username": "USERNAME",
            "password": "PASSWORD",
            "game_app_ids": "GAME_APP_IDS",
            "filter_trading_cards": "FILTER_TRADING_CARDS",
            "use_owned_games": "USE_OWNED_GAMES",
            "filter_completed_card_drops": "FILTER_COMPLETED_CARD_DROPS",
            "exclude_app_ids": "EXCLUDE_APP_IDS",
            "max_games_to_idle": "MAX_GAMES_TO_IDLE",
            "idling_backend": "IDLING_BACKEND",
            "steam_utility_path": "STEAM_UTILITY_PATH",
            "steam_api_key": "STEAM_API_KEY",
            "steam_web_cookies": "STEAM_WEB_COOKIES",
            "log_level": "LOG_LEVEL",
            "log_file": "LOG_FILE",
            "api_timeout": "API_TIMEOUT",
            "rate_limit_delay": "RATE_LIMIT_DELAY",
            "enable_card_cache": "ENABLE_CARD_CACHE",
            "card_cache_path": "CARD_CACHE_PATH",
            "card_cache_ttl_days": "CARD_CACHE_TTL_DAYS",
            "max_checks": "MAX_CHECKS",
            "skip_failures": "SKIP_FAILURES",
            "enable_encryption": "ENABLE_ENCRYPTION",
        }

        lines: list[str] = []
        for field_name, env_name in env_mapping.items():
            value = data.get(field_name)
            if value is None:
                lines.append(f"{env_name}=")
                continue

            if isinstance(value, list) and value and isinstance(value[0], dict):
                rendered = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
            elif isinstance(value, list):
                rendered = ",".join(str(item) for item in value)
            elif isinstance(value, dict):
                rendered = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
            elif isinstance(value, bool):
                rendered = "true" if value else "false"
            else:
                rendered = str(value)

            lines.append(f"{env_name}={rendered}")

        target.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return target
