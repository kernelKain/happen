"""Uvicorn entrypoint. The process exits when configuration is invalid."""

from happen_api.app import create_app

app = create_app()
