"""Tool permission manifest + risk enforcement."""
from __future__ import annotations

from core.shared.types import RiskLevel
from .base_tool import BaseTool

# Risk levels that always demand explicit user confirmation before running.
CONFIRM_REQUIRED = {RiskLevel.HIGH, RiskLevel.CRITICAL}


def needs_confirmation(tool: BaseTool) -> bool:
    return tool.risk_level in CONFIRM_REQUIRED


def permission_manifest(tools: list[BaseTool]) -> list[dict]:
    return [
        {"tool": t.name, "risk": t.risk_level.value,
         "confirm": needs_confirmation(t)}
        for t in tools
    ]
