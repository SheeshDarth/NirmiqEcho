"""Tiny async pub/sub bus for internal events + WebSocket fan-out."""
from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any, Awaitable, Callable

from core.shared.logger import get_logger

log = get_logger(__name__)

Handler = Callable[[dict[str, Any]], Awaitable[None]]


class EventBus:
    def __init__(self) -> None:
        self._subs: dict[str, list[Handler]] = defaultdict(list)
        self._wildcard: list[Handler] = []

    def subscribe(self, event: str, handler: Handler) -> None:
        if event == "*":
            self._wildcard.append(handler)
        else:
            self._subs[event].append(handler)

    async def emit(self, event: str, payload: dict[str, Any]) -> None:
        handlers = list(self._subs.get(event, [])) + list(self._wildcard)
        if not handlers:
            return
        results = await asyncio.gather(
            *(h({"event": event, "payload": payload}) for h in handlers),
            return_exceptions=True,
        )
        for r in results:
            if isinstance(r, Exception):
                log.error("eventbus.handler_error", event=event, error=str(r))
