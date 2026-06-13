"""Master coordinator — intent in, plan + execute + verify out."""
from __future__ import annotations

import time

from core.engine.event_bus import EventBus
from core.engine.executor import Executor
from core.engine.planner import Planner
from core.engine.verifier import Verifier
from core.memory.store import MemoryStore
from core.models.model_router import ModelRouter
from core.shared.exceptions import PlanningError
from core.shared.logger import get_logger
from core.shared.types import EngineMode
from core.tools.registry import ToolRegistry

log = get_logger(__name__)


class Coordinator:
    def __init__(self, bus: EventBus | None = None,
                 registry: ToolRegistry | None = None,
                 router: ModelRouter | None = None,
                 memory: MemoryStore | None = None):
        self.bus = bus or EventBus()
        self.registry = registry or ToolRegistry()
        self.router = router or ModelRouter()
        self.memory = memory or MemoryStore()
        self.planner = Planner(self.router, self.registry)
        self.executor = Executor(self.registry, self.bus, Verifier(), self.memory)

    async def handle_intent(self, intent: str,
                            mode: EngineMode = EngineMode.ASSISTANT) -> dict:
        intent = intent.strip()
        if not intent:
            return {"success": False, "error": "empty intent"}

        # Dictation mode never plans — it just types.
        if mode == EngineMode.DICTATION:
            res = await self.registry.execute("paste_text", {"text": intent})
            return {"success": res.success, "dictated": intent}

        started = time.monotonic()
        try:
            plan = await self.planner.plan(intent, self._memory_context())
        except PlanningError as e:
            log.warning("coordinator.plan_failed", intent=intent, error=str(e))
            await self.bus.emit("response.text", {
                "text": f"I couldn't plan that: {e}"})
            self.memory.record_command(intent, None, None, "failed")
            return {"success": False, "error": str(e)}

        await self.bus.emit("plan.created", {"plan": plan.model_dump(mode="json")})

        # Developer mode: never auto-execute — force confirmation on everything
        if mode == EngineMode.DEVELOPER:
            plan.requires_confirmation = True

        result = await self.executor.execute(plan)
        duration_ms = int((time.monotonic() - started) * 1000)
        self.memory.record_command(
            intent, None, plan.plan_id,
            "success" if result.get("success") else "failed", duration_ms)
        await self.bus.emit("response.text", {
            "text": result.get("summary", ""), "plan_id": plan.plan_id})
        return result

    def confirm(self, plan_id: str, approved: bool) -> None:
        self.executor.confirm(plan_id, approved)

    def _memory_context(self) -> str:
        prefs = self.memory.list("preference", limit=5)
        projects = self.memory.list("project", limit=5)
        bits = [f"{p.key}={p.value}" for p in prefs]
        bits += [f"project:{p.key}={p.value}" for p in projects]
        return "; ".join(bits)
