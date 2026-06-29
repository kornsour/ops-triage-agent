"""FastAPI backend for the triage system."""

from .server import app, create_app

__all__ = ["app", "create_app"]
