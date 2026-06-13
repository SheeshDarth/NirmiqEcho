"""Executes an ExecutionPlan step by step, with verification + confirmation gating."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from core.engine.event_bus import EventBus
from core.engine.verifier import Verifier
from core.shared.logger import get_logger
from core.shared.types import ExecutionPlan, RiskLevel, StepStatus
from core.tools.registry import ToolRegistry

log = get_logger(__name__)


class Executor:
    def __init__(self, registry: ToolRegistry, bus: EventBus,
                 verifier: Verifier | None = None, memory=None):
        self._registry = registry
        self._bus = bus
        self._verifier = verifier or Verifier()
        self._memory = memory
        # plan_id -> asyncio.Event used to resume after confirmation
        self._pending: dict[str, asyncio.Event] = {}
        self._confirmed: dict[str, bool] = {}

    def confirm(self, plan_id: str, approved: bool) -> None:
        """Called by the API when the user answers a confirmation prompt."""
        self._confirmed[plan_id] = approved
        ev = self._pending.get(plan_id)
        if ev:
            ev.set()

    async def execute(self, plan: ExecutionPlan) -> dict:
        ok_all = True
        for step in plan.steps:
            # Gate high-risk steps behind explicit confirmation
            if step.risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL):
                approved = await self._await_confirmation(plan, step)
                if not approved:
                    step.status = StepStatus.SKIPPED
                    await self._emit_step(plan, step)
                    await self._bus.emit("plan.completed", {
                        "plan_id": plan.plan_id, "success": False,
                        "summary": "Cancelled by user at confirmation."})
                    return {"success": False, "cancelled": True}

            step.status = StepStatus.RUNNING
            step.started_at = datetime.now(timezone.utc)
            await self._emit_step(plan, step)

            result = await self._registry.execute(step.tool_name, step.tool_args)
            verified = self._verifier.verify(step, result)

            step.completed_at = datetime.now(timezone.utc)
            step.result = result.data
            step.error = result.error
            step.status = StepStatus.SUCCESS if verified else StepStatus.FAILED
            ok_all = ok_all and verified
            await self._emit_step(plan, step)

            if self._memory:
                self._memory.record_step(plan.plan_id, step.step_number,
                                         step.tool_name, step.tool_args,
                                         result.data, step.status.value)
            if not verified:
                break  # stop the plan on first failure

        summary = self._summarize(plan, ok_all)
        await self._bus.emit("plan.completed", {
            "plan_id": plan.plan_id, "success": ok_all, "summary": summary})
        return {"success": ok_all, "summary": summary}

    async def _await_confirmation(self, plan, step) -> bool:
        ev = asyncio.Event()
        self._pending[plan.plan_id] = ev
        step.status = StepStatus.AWAITING_CONFIRMATION
        await self._emit_step(plan, step)
        await self._bus.emit("confirmation.required", {
            "plan_id": plan.plan_id,
            "message": plan.confirmation_message or
                       f"This will run '{step.tool_name}'. Proceed?",
            "action_summary": step.description,
        })
        try:
            await asyncio.wait_for(ev.wait(), timeout=120)
        except asyncio.TimeoutError:
            return False
        finally:
            self._pending.pop(plan.plan_id, None)
        return self._confirmed.pop(plan.plan_id, False)

    async def _emit_step(self, plan, step) -> None:
        await self._bus.emit("plan.step_update", {
            "plan_id": plan.plan_id, "step_id": step.step_id,
            "status": step.status.value, "result": step.result,
            "error": step.error,
        })

    @staticmethod
    def _summarize(plan: ExecutionPlan, ok: bool) -> str:
        done = sum(1 for s in plan.steps if s.status == StepStatus.SUCCESS)
        if ok:
            return f"Completed {done} step(s) for: {plan.raw_intent}"
        failed = next((s for s in plan.steps if s.status == StepStatus.FAILED), None)
        if failed:
            return f"Failed at step {failed.step_number} ({failed.tool_name}): {failed.error}"
        return "Plan did not complete."
