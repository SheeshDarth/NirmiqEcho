"""Note tools: take_note, list_notes, search_notes (Markdown in ~/NirmiqNotes)."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from core.config.settings import get_settings
from core.shared.types import RiskLevel, ToolResult
from core.tools.base_tool import BaseTool


def _notes_file() -> Path:
    d = get_settings().notes_dir
    d.mkdir(parents=True, exist_ok=True)
    return d / "notes.md"


class TakeNoteTool(BaseTool):
    name = "take_note"
    description = "Append a timestamped note to the user's notes file."
    risk_level = RiskLevel.SAFE
    args_hint = "text"

    def validate_args(self, args: dict) -> tuple[bool, str]:
        return (bool(args.get("text")), "text is required")

    async def execute(self, args: dict) -> ToolResult:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M")
        line = f"- [{ts}] {str(args['text']).strip()}\n"
        f = _notes_file()
        with open(f, "a", encoding="utf-8") as fh:
            fh.write(line)
        return ToolResult(success=True, data={"note": line.strip()}, verified=True)


class ListNotesTool(BaseTool):
    name = "list_notes"
    description = "Return the most recent notes."
    risk_level = RiskLevel.SAFE
    args_hint = "count"

    async def execute(self, args: dict) -> ToolResult:
        n = int(args.get("count", 5))
        f = _notes_file()
        if not f.exists():
            return ToolResult(success=True, data={"notes": []}, verified=True)
        lines = [l.strip() for l in f.read_text(encoding="utf-8").splitlines() if l.strip()]
        return ToolResult(success=True, data={"notes": lines[-n:]}, verified=True)


class SearchNotesTool(BaseTool):
    name = "search_notes"
    description = "Full-text search across the user's notes."
    risk_level = RiskLevel.SAFE
    args_hint = "query"

    def validate_args(self, args: dict) -> tuple[bool, str]:
        return (bool(args.get("query")), "query is required")

    async def execute(self, args: dict) -> ToolResult:
        q = str(args["query"]).lower()
        f = _notes_file()
        if not f.exists():
            return ToolResult(success=True, data={"matches": []}, verified=True)
        matches = [l.strip() for l in f.read_text(encoding="utf-8").splitlines()
                   if q in l.lower()]
        return ToolResult(success=True, data={"matches": matches}, verified=True)
