"""Abstract base class every tool implements."""
from __future__ import annotations

from abc import ABC, abstractmethod

from core.shared.types import RiskLevel, ToolResult


class BaseTool(ABC):
    name: str = ""
    description: str = ""
    risk_level: RiskLevel = RiskLevel.SAFE
    args_hint: str = ""   # e.g. "app_name" — tells the planner the arg keys

    @abstractmethod
    async def execute(self, args: dict) -> ToolResult:
        """Perform the tool's action and return a verified ToolResult."""

    def validate_args(self, args: dict) -> tuple[bool, str]:
        """Return (is_valid, error_message). Override for required args."""
        return True, ""

    def requires_confirmation(self) -> bool:
        return self.risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL)

    def manifest(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "risk_level": self.risk_level.value,
        }
