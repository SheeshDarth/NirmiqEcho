"""Timer tool: set_timer (asyncio-based, fires an event_bus event)."""
from __future__ import annotations

import asyncio

from core.shared.types import RiskLevel, ToolResult
from core.tools.base_tool import BaseTool


class SetTimerTool(BaseTool):
    name = "set_timer"
    description = "Set a timer for N seconds/minutes; fires timer.fired when done."
    risk_level = RiskLevel.SAFE
    args_hint = "minutes, duration_s, label"

    def __init__(self, on_fire=None):
        self._on_fire = on_fire  # callable(label, seconds) | None

    def validate_args(self, args: dict) -> tuple[bool, str]:
        return ("duration_s" in args or "minutes" in args,
                "duration_s or minutes required")

    async def execute(self, args: dict) -> ToolResult:
        seconds = int(args.get("duration_s", 0)) or int(args.get("minutes", 0)) * 60
        if seconds <= 0:
            return ToolResult(success=False, error="duration must be positive")
        label = str(args.get("label", f"{seconds}s timer"))

        async def _run():
            await asyncio.sleep(seconds)
            if self._on_fire:
                self._on_fire(label, seconds)

        asyncio.create_task(_run())
        return ToolResult(success=True, data={"label": label, "seconds": seconds},
                          verified=True)
