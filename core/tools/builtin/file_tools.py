"""File tools: search_files, create_file, move_file, delete_file."""
from __future__ import annotations

import os
import shutil
from pathlib import Path

from core.shared.types import RiskLevel, ToolResult
from core.tools.base_tool import BaseTool

_ROOTS = [Path.home() / d for d in
          ("Desktop", "Documents", "Downloads", "Pictures", "Music", "Videos")]

# Directories a write must never touch — auto-run / system locations are a
# persistence and privilege vector. create_file runs without confirmation, so
# this guard is its primary protection.
_BLOCKED_WRITE_DIRS = [
    Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows"
        / "Start Menu" / "Programs" / "Startup",
    Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "Microsoft"
        / "Windows" / "Start Menu" / "Programs" / "StartUp",
    Path(os.environ.get("WINDIR", r"C:\Windows")),
    Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")),
    Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")),
]
# File types that auto-execute or hijack execution — refuse to create them.
_BLOCKED_WRITE_EXTS = {".bat", ".cmd", ".com", ".scr", ".ps1", ".vbs", ".vbe",
                       ".js", ".jse", ".wsf", ".wsh", ".hta", ".msi", ".reg",
                       ".dll", ".sys", ".lnk", ".pif"}


def _safe_write_target(path: Path) -> tuple[bool, str]:
    """Validate a write/move destination against sensitive dirs + exec types."""
    try:
        resolved = path.expanduser().resolve()
    except Exception:
        return False, "invalid path"
    for blocked in _BLOCKED_WRITE_DIRS:
        try:
            if blocked and (resolved == blocked.resolve()
                            or blocked.resolve() in resolved.parents):
                return False, "writing to a system/startup location is not allowed"
        except Exception:
            continue
    if resolved.suffix.lower() in _BLOCKED_WRITE_EXTS:
        return False, f"creating {resolved.suffix} files is not allowed for safety"
    return True, ""


class SearchFilesTool(BaseTool):
    name = "search_files"
    description = "Search the user's folders for files matching a name fragment."
    risk_level = RiskLevel.SAFE
    args_hint = "query, limit"

    def validate_args(self, args: dict) -> tuple[bool, str]:
        return (bool(args.get("query")), "query is required")

    async def execute(self, args: dict) -> ToolResult:
        q = str(args["query"]).lower().strip()
        limit = int(args.get("limit", 10))
        hits: list[str] = []
        for root in _ROOTS:
            if not root.exists():
                continue
            try:
                for p in root.rglob("*"):
                    if p.is_file() and q in p.name.lower():
                        hits.append(str(p))
                        if len(hits) >= limit:
                            break
            except (PermissionError, OSError):
                continue
            if len(hits) >= limit:
                break
        return ToolResult(success=True, data={"matches": hits}, verified=True)


class CreateFileTool(BaseTool):
    name = "create_file"
    description = "Create a text file with given content (won't overwrite)."
    risk_level = RiskLevel.LOW
    args_hint = "path, content"

    def validate_args(self, args: dict) -> tuple[bool, str]:
        return (bool(args.get("path")), "path is required")

    async def execute(self, args: dict) -> ToolResult:
        path = Path(args["path"]).expanduser()
        ok, msg = _safe_write_target(path)
        if not ok:
            return ToolResult(success=False, error=msg)
        if path.exists():
            return ToolResult(success=False, error="file already exists")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(args.get("content", "")), encoding="utf-8")
        return ToolResult(success=True, data={"created": str(path)},
                          verified=path.exists())


class MoveFileTool(BaseTool):
    name = "move_file"
    description = "Move a file from source to destination."
    risk_level = RiskLevel.MEDIUM
    args_hint = "source, destination"

    def validate_args(self, args: dict) -> tuple[bool, str]:
        if not args.get("source") or not args.get("destination"):
            return False, "source and destination are required"
        return True, ""

    async def execute(self, args: dict) -> ToolResult:
        src = Path(args["source"]).expanduser()
        dst = Path(args["destination"]).expanduser()
        if not src.exists():
            return ToolResult(success=False, error="source does not exist")
        ok, msg = _safe_write_target(dst if dst.suffix else dst / src.name)
        if not ok:
            return ToolResult(success=False, error=msg)
        final = shutil.move(str(src), str(dst))
        return ToolResult(success=True, data={"moved_to": final},
                          verified=Path(final).exists())


class DeleteFileTool(BaseTool):
    name = "delete_file"
    description = "Send a file to the Recycle Bin (never a permanent delete)."
    risk_level = RiskLevel.HIGH
    args_hint = "path"

    def validate_args(self, args: dict) -> tuple[bool, str]:
        return (bool(args.get("path")), "path is required")

    async def execute(self, args: dict) -> ToolResult:
        path = Path(args["path"]).expanduser()
        if not path.exists():
            return ToolResult(success=False, error="file does not exist")
        try:
            from send2trash import send2trash
            send2trash(str(path))
        except ImportError:
            return ToolResult(success=False,
                              error="send2trash not installed; refusing permanent delete")
        return ToolResult(success=True, data={"trashed": str(path)},
                          verified=not path.exists())
