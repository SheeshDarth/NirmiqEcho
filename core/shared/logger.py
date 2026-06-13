"""Structured logging via structlog, with a graceful stdlib fallback."""
from __future__ import annotations

import logging
import sys

try:
    import structlog
    _HAS_STRUCTLOG = True
except ImportError:  # pragma: no cover - structlog is a declared dep
    _HAS_STRUCTLOG = False

_CONFIGURED = False


def configure_logging(level: str = "INFO") -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    log_level = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=log_level,
    )
    if _HAS_STRUCTLOG:
        structlog.configure(
            processors=[
                structlog.processors.add_log_level,
                structlog.processors.TimeStamper(fmt="iso"),
                structlog.dev.ConsoleRenderer(),
            ],
            wrapper_class=structlog.make_filtering_bound_logger(log_level),
            logger_factory=structlog.PrintLoggerFactory(),
            cache_logger_on_first_use=True,
        )
    # Quieten noisy third parties
    for noisy in ("faster_whisper", "ctranslate2", "numba", "httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    _CONFIGURED = True


def get_logger(name: str):
    """Return a structured logger (structlog) or a stdlib shim."""
    if not _CONFIGURED:
        configure_logging()
    if _HAS_STRUCTLOG:
        return structlog.get_logger(name)
    return _StdlibShim(logging.getLogger(name))


class _StdlibShim:
    """Lets call sites use structlog's kwargs style on plain logging."""

    def __init__(self, logger: logging.Logger):
        self._log = logger

    def _fmt(self, event: str, **kw) -> str:
        extra = " ".join(f"{k}={v!r}" for k, v in kw.items())
        return f"{event} {extra}".strip()

    def debug(self, event: str, **kw): self._log.debug(self._fmt(event, **kw))
    def info(self, event: str, **kw): self._log.info(self._fmt(event, **kw))
    def warning(self, event: str, **kw): self._log.warning(self._fmt(event, **kw))
    def error(self, event: str, **kw): self._log.error(self._fmt(event, **kw))
    def exception(self, event: str, **kw): self._log.exception(self._fmt(event, **kw))
