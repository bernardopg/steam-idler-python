"""Structured logging configuration with rich formatting and file output."""

__all__ = ["SteamIdleLogger", "setup_logging"]

import logging
from logging.handlers import RotatingFileHandler

from rich.console import Console
from rich.logging import RichHandler

# Cap the on-disk log so a long-running idle session can't grow it unbounded.
_LOG_MAX_BYTES = 10 * 1024 * 1024
_LOG_BACKUP_COUNT = 3


class SteamIdleLogger:
    """Custom logger with rich formatting and file output support."""

    def __init__(
        self,
        name: str = "steam_idle_bot",
        level: str = "INFO",
        log_file: str | None = None,
        console_output: bool = True,
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

        if console_output:
            # Console handler with rich formatting
            console_handler = RichHandler(
                console=Console(stderr=True),
                show_time=True,
                show_path=False,
                rich_tracebacks=True,
            )
            console_handler.setLevel(getattr(logging, level.upper()))
            self.logger.addHandler(console_handler)

        # File handler if specified. Rotate so a long-running idle session does
        # not grow a single log file without bound.
        if log_file:
            file_handler = RotatingFileHandler(
                log_file,
                maxBytes=_LOG_MAX_BYTES,
                backupCount=_LOG_BACKUP_COUNT,
                encoding="utf-8",
            )
            file_handler.setFormatter(formatter)
            file_handler.setLevel(getattr(logging, level.upper()))
            self.logger.addHandler(file_handler)

    def get_logger(self) -> logging.Logger:
        """Return the configured logger."""
        return self.logger


def setup_logging(
    level: str = "INFO",
    log_file: str | None = None,
    *,
    console_output: bool = True,
) -> logging.Logger:
    """Set up global logging configuration."""
    logger = SteamIdleLogger(
        level=level,
        log_file=log_file,
        console_output=console_output,
    ).get_logger()

    # Log startup information
    logger.info("Steam Idle Bot starting...")
    logger.debug(f"Logging level: {level}")
    if log_file:
        logger.debug(f"Log file: {log_file}")

    return logger
