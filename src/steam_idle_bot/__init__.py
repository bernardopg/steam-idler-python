"""Steam Idle Bot - A modern Steam game idling tool with trading card support."""

__version__ = "1.0.0"
__author__ = "Steam Idle Bot Team"
__description__ = "Steam Idle Bot with Trading Card Support"

from .config.settings import Settings
from .main import main
from .steam.client import SteamClientWrapper

__all__ = ["Settings", "SteamClientWrapper", "main"]
