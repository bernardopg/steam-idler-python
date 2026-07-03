"""Web UI backend (FastAPI + React frontend) for the Steam Idle Bot."""

__all__ = ["BotController", "create_app", "launch_web"]

from .controller import BotController
from .server import create_app, launch_web
