"""Misc tools: calculate (offline math), launch_project (memory-backed)."""
from __future__ import annotations

import ast
import operator
import re

from core.shared.types import RiskLevel, ToolResult
from core.tools.base_tool import BaseTool

_BIN = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
        ast.Div: operator.truediv, ast.Pow: operator.pow, ast.Mod: operator.mod,
        ast.FloorDiv: operator.floordiv}
_UN = {ast.UAdd: operator.pos, ast.USub: operator.neg}

_WORD_OPS = [(r"\bplus\b|\band\b", "+"), (r"\bminus\b", "-"),
             (r"\btimes\b|\bmultiplied by\b", "*"),
             (r"\bdivided by\b|\bover\b", "/"),
             (r"\bto the power of\b|\bpower\b", "**")]


def _safe_eval(expr: str) -> float:
    def ev(node):
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in _BIN:
            return _BIN[type(node.op)](ev(node.left), ev(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in _UN:
            return _UN[type(node.op)](ev(node.operand))
        raise ValueError("disallowed expression")
    return ev(ast.parse(expr, mode="eval"))


class CalculateTool(BaseTool):
    name = "calculate"
    description = "Evaluate a spoken or written arithmetic expression, offline."
    risk_level = RiskLevel.SAFE
    args_hint = "expression"

    def validate_args(self, args: dict) -> tuple[bool, str]:
        return (bool(args.get("expression")), "expression is required")

    async def execute(self, args: dict) -> ToolResult:
        t = str(args["expression"]).lower().strip().rstrip("?.!")
        m = re.search(r"square root of\s+(.+)", t)
        if m:
            t = f"({m.group(1)})**0.5"
        for pat, sym in _WORD_OPS:
            t = re.sub(pat, f" {sym} ", t)
        cleaned = re.sub(r"[^0-9+\-*/%.()\s]", "", t).strip()
        if not cleaned or not re.search(r"\d", cleaned):
            return ToolResult(success=False, error="no expression found")
        try:
            val = _safe_eval(cleaned)
        except Exception:
            return ToolResult(success=False, error="could not evaluate")
        out = int(val) if isinstance(val, float) and val.is_integer() else round(val, 6)
        return ToolResult(success=True, data={"result": out}, verified=True)


class LaunchProjectTool(BaseTool):
    name = "launch_project"
    description = "Open a saved project path in the configured editor."
    risk_level = RiskLevel.SAFE
    args_hint = "project"

    def __init__(self, memory=None):
        self._memory = memory

    def validate_args(self, args: dict) -> tuple[bool, str]:
        return (bool(args.get("project")), "project is required")

    async def execute(self, args: dict) -> ToolResult:
        import os
        import shutil
        import subprocess
        proj = str(args["project"]).lower().strip()
        path = None
        if self._memory:
            entry = self._memory.get("project", proj)
            if entry:
                path = entry.value
        if not path:
            return ToolResult(success=False,
                              error=f"No saved path for project '{proj}'. "
                                    f"Add one to project memory first.")
        code = shutil.which("code")
        if code:
            subprocess.Popen([code, path], shell=False)
        else:
            os.startfile(path)
        return ToolResult(success=True, data={"opened": path}, verified=True)
