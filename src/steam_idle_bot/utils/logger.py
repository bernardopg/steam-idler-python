"""Structured logging configuration with rich formatting and file output."""

import logging
from typing import Optional

from rich.console import Console
from rich.logging import RichHandler


class SteamIdleLogger:
    """Custom logger with rich formatting and file output support."""

    def __init__(
        self,
        name: str = "steam_idle_bot",
        level: str = "INFO",
        log_file: Optional[str] = None,
    ):
        self.logger = logging.getLogger(name)
        self.logger.setLevel(getattr(logging, level.upper()))

        # Clear existing handlers
        self.logger.handlers.clear()

        # Create formatter
        formatter = logging.Formatter(
            fmt="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        # Console handler with rich formatting
        console_handler = RichHandler(
            console=Console(stderr=True),
            show_time=True,
            show_path=False,
            rich_tracebacks=True,
        )
        console_handler.setLevel(getattr(logging, level.upper()))
        self.logger.addHandler(console_handler)

        # File handler if specified
        if log_file:
            file_handler = logging.FileHandler(log_file)
            file_handler.setFormatter(formatter)
            file_handler.setLevel(getattr(logging, level.upper()))
            self.logger.addHandler(file_handler)

    def get_logger(self) -> logging.Logger:
        """Return the configured logger."""
        return self.logger


def setup_logging(
    level: str = "INFO", log_file: Optional[str] = None
) -> logging.Logger:
    """Set up global logging configuration."""
    logger = SteamIdleLogger(level=level, log_file=log_file).get_logger()

    # Log startup information
    logger.info("Steam Idle Bot starting...")
    logger.debug(f"Logging level: {level}")
    if log_file:
        logger.debug(f"Log file: {log_file}")

    return logger
