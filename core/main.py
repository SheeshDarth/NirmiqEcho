"""Nirmiq Echo backend entry point. Starts the FastAPI + WebSocket server."""
from __future__ import annotations

import uvicorn

from core.api.server import create_app
from core.config.settings import get_settings
from core.shared.logger import configure_logging, get_logger


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    log = get_logger(__name__)
    log.info("nirmiq.start", http_port=settings.server.http_port)
    app = create_app()
    uvicorn.run(app, host=settings.server.host,
                port=settings.server.http_port, log_level="warning")


if __name__ == "__main__":
    main()
