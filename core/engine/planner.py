"""LLM-backed planner. Always returns a structured ExecutionPlan, never free text."""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone

from core.models.model_router import ModelRouter
from core.shared.exceptions import PlanningError
from core.shared.logger import get_logger
from core.shared.types import ExecutionPlan, PlanStep, RiskLevel
from core.tools.registry import ToolRegistry

log = get_logger(__name__)

PLANNER_SYSTEM_PROMPT = """You are the planning engine for Nirmiq Echo, a local voice operating system.
Convert the user's natural-language intent into a precise, ordered execution plan.

You MUST respond with ONLY valid JSON, no markdown, matching this schema:
{
  "steps": [
    {
      "step_number": 1,
      "description": "Human-readable description",
      "tool_name": "exact_tool_name",
      "tool_args": { "arg_key": "arg_value" },
      "risk_level": "safe|low|medium|high|critical"
    }
  ],
  "requires_confirmation": false,
  "confirmation_message": null
}

Available tools:
{tool_list}

Rules:
- Use ONLY tools from the available list, with their exact names.
- Keep the plan minimal — no unnecessary steps.
- If any step is high or critical risk, set requires_confirmation to true and
  write a clear one-sentence confirmation_message.
- If you cannot build a valid plan, return {"error": "reason"}.
- Return ONLY the JSON object. No explanations, no markdown fences."""


class Planner:
    def __init__(self, router: ModelRouter, registry: ToolRegistry):
        self._router = router
        self._registry = registry

    async def plan(self, intent: str, memory_context: str = "") -> ExecutionPlan:
        system = PLANNER_SYSTEM_PROMPT.replace(
            "{tool_list}", self._registry.tool_list_for_planner())
        user = intent if not memory_context else f"{intent}\n\nContext:\n{memory_context}"

        raw = await self._router.complete("planning", system, user, json_mode=True)
        data = self._parse_json(raw)

        if "error" in data:
            raise PlanningError(str(data["error"]))

        steps_in = data.get("steps", [])
        if not isinstance(steps_in, list) or not steps_in:
            raise PlanningError("planner returned no steps")

        steps: list[PlanStep] = []
        valid_tools = set(self._registry.tools.keys())
        for i, s in enumerate(steps_in, start=1):
            tool_name = str(s.get("tool_name", "")).strip()
            if tool_name not in valid_tools:
                log.warning("planner.unknown_tool", tool=tool_name)
                continue
            try:
                risk = RiskLevel(str(s.get("risk_level", "safe")).lower())
            except ValueError:
                risk = RiskLevel.SAFE
            steps.append(PlanStep(
                step_id=str(uuid.uuid4()),
                step_number=int(s.get("step_number", i)),
                description=str(s.get("description", tool_name)),
                tool_name=tool_name,
                tool_args=dict(s.get("tool_args", {})),
                risk_level=risk,
            ))

        if not steps:
            raise PlanningError("no valid steps after tool validation")

        requires_conf = bool(data.get("requires_confirmation", False)) or any(
            st.risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL) for st in steps)

        return ExecutionPlan(
            plan_id=str(uuid.uuid4()),
            raw_intent=intent,
            steps=steps,
            created_at=datetime.now(timezone.utc),
            requires_confirmation=requires_conf,
            confirmation_message=data.get("confirmation_message"),
        )

    @staticmethod
    def _parse_json(raw: str) -> dict:
        raw = raw.strip()
        # strip markdown fences if a model adds them despite instructions
        if raw.startswith("```"):
            raw = re.sub(r"^```[a-zA-Z]*\n?|\n?```$", "", raw).strip()
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            # last-ditch: extract the first {...} block
            m = re.search(r"\{.*\}", raw, re.DOTALL)
            if m:
                try:
                    return json.loads(m.group(0))
                except json.JSONDecodeError:
                    pass
        raise PlanningError(f"planner did not return valid JSON: {raw[:200]}")
