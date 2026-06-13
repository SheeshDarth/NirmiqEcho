"""Core smoke tests — memory, tool registry, and a few tool executions.

These run offline (no Ollama). The planner is exercised separately in
tests/test_planner.py which is skipped when Ollama is unreachable.
"""
import tempfile
from pathlib import Path

import pytest

from core.memory.store import MemoryStore
from core.tools.registry import ToolRegistry


def test_memory_roundtrip():
    with tempfile.TemporaryDirectory() as d:
        store = MemoryStore(db_path=Path(d) / "t.db")
        try:
            store.set("preference", "editor", "vscode")
            entry = store.get("preference", "editor")
            assert entry is not None
            assert entry.value == "vscode"
            assert store.delete("preference", "editor") is True
            assert store.get("preference", "editor") is None
        finally:
            store.close()


def test_memory_short_term_isolated():
    with tempfile.TemporaryDirectory() as d:
        store = MemoryStore(db_path=Path(d) / "t.db")
        try:
            store.set("short", "scratch", {"a": 1})
            assert store.get("short", "scratch").value == {"a": 1}
        finally:
            store.close()


def test_registry_loads_all_tools():
    reg = ToolRegistry()
    assert len(reg.tools) >= 20
    assert "open_app" in reg.tools
    assert "delete_file" in reg.tools


def test_delete_file_is_high_risk():
    reg = ToolRegistry()
    assert reg.get("delete_file").requires_confirmation() is True
    assert reg.get("open_url").requires_confirmation() is False


@pytest.mark.asyncio
async def test_calculate_tool():
    reg = ToolRegistry()
    res = await reg.execute("calculate", {"expression": "what is 45 plus 30"})
    assert res.success
    assert res.data["result"] == 75


@pytest.mark.asyncio
async def test_unknown_tool_returns_error():
    reg = ToolRegistry()
    res = await reg.execute("does_not_exist", {})
    assert not res.success
    assert "Unknown tool" in res.error


@pytest.mark.asyncio
async def test_take_and_list_note():
    reg = ToolRegistry()
    r1 = await reg.execute("take_note", {"text": "pytest note"})
    assert r1.success
    r2 = await reg.execute("list_notes", {"count": 5})
    assert any("pytest note" in n for n in r2.data["notes"])


@pytest.mark.asyncio
async def test_terminal_blocklist():
    reg = ToolRegistry()
    res = await reg.execute("terminal_executor", {"command": "shutdown /s"})
    assert not res.success
    assert "blocklist" in (res.error or "").lower()
