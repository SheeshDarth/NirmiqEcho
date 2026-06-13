"""Tool registry — discovers, registers, and dispatches all tools."""
from __future__ import annotations

from core.shared.logger import get_logger
from core.shared.types import ToolResult
from .base_tool import BaseTool

log = get_logger(__name__)


class ToolRegistry:
    def __init__(self) -> None:
        self.tools: dict[str, BaseTool] = {}
        self._load_builtin()

    def register(self, tool: BaseTool) -> None:
        if not tool.name:
            raise ValueError(f"Tool {tool.__class__.__name__} has no name")
        self.tools[tool.name] = tool

    def get(self, name: str) -> BaseTool | None:
        return self.tools.get(name)

    def manifest(self) -> list[dict]:
        return [t.manifest() for t in self.tools.values()]

    def tool_list_for_planner(self) -> str:
        """Compact textual catalogue injected into the planner prompt."""
        lines = []
        for t in self.tools.values():
            args = f"  args: {{{t.args_hint}}}" if t.args_hint else "  args: {}"
            lines.append(f"- {t.name} ({t.risk_level.value}): {t.description}{args}")
        return "\n".join(lines)

    async def execute(self, name: str, args: dict) -> ToolResult:
        tool = self.get(name)
        if not tool:
            return ToolResult(success=False, error=f"Unknown tool: {name}")
        valid, msg = tool.validate_args(args)
        if not valid:
            return ToolResult(success=False, error=f"Invalid args: {msg}")
        try:
            result = await tool.execute(args)
            log.info("tool.executed", tool=name, success=result.success)
            return result
        except PermissionError as e:
            log.error("tool.permission_denied", tool=name, error=str(e))
            return ToolResult(success=False, error="Permission denied")
        except Exception as e:  # noqa: BLE001 - surfaced as a failed ToolResult
            log.exception("tool.unexpected_error", tool=name, error=str(e))
            return ToolResult(success=False,
                              error=f"Unexpected error: {type(e).__name__}: {e}")

    def _load_builtin(self) -> None:
        from .builtin import all_builtin_tools
        for tool in all_builtin_tools():
            self.register(tool)
        log.info("tools.loaded", count=len(self.tools))
