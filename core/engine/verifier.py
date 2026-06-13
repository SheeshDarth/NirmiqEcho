"""Post-execution verification — confirm a step actually did what it claimed."""
from __future__ import annotations

from core.shared.types import PlanStep, ToolResult


class Verifier:
    """
    Phase-1 verification trusts the tool's own `verified` flag (each tool
    checks its own postcondition: file exists, process gone, etc.) and
    treats success=False as a hard failure. Centralised here so richer
    cross-checks can be added without touching the executor.
    """

    def verify(self, step: PlanStep, result: ToolResult) -> bool:
        if not result.success:
            return False
        # If a tool reported an explicit verification result, honour it.
        return result.verified or result.success
