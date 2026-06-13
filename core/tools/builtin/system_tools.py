"""System tools: volume_control, window_manager, capture_screen,
clipboard (copy_text, paste_text)."""
from __future__ import annotations

import subprocess
import tempfile
import time
from pathlib import Path

from core.shared.types import RiskLevel, ToolResult
from core.tools.base_tool import BaseTool

_NO_WINDOW = 0x08000000


class VolumeControlTool(BaseTool):
    name = "volume_control"
    description = "Set or step the system volume (action: up|down|mute, or level 0-100)."
    risk_level = RiskLevel.SAFE
    args_hint = "action, level"

    async def execute(self, args: dict) -> ToolResult:
        try:
            import keyboard
        except ImportError:
            return ToolResult(success=False, error="keyboard module unavailable")
        action = str(args.get("action", "")).lower()
        level = args.get("level")
        if level is not None:
            lvl = max(0, min(100, int(level)))
            for _ in range(50):
                keyboard.send("volume down")
            for _ in range(lvl // 2):
                keyboard.send("volume up")
            return ToolResult(success=True, data={"level": lvl}, verified=True)
        key = {"up": "volume up", "down": "volume down", "mute": "volume mute"}.get(action)
        if not key:
            return ToolResult(success=False, error="action must be up|down|mute or give level")
        for _ in range(int(args.get("steps", 2))):
            keyboard.send(key)
        return ToolResult(success=True, data={"action": action}, verified=True)


class WindowManagerTool(BaseTool):
    name = "window_manager"
    description = "List or focus/minimize/maximize windows by title fragment."
    risk_level = RiskLevel.LOW
    args_hint = "action, title"

    async def execute(self, args: dict) -> ToolResult:
        try:
            import pygetwindow as gw
        except ImportError:
            return ToolResult(success=False, error="pygetwindow unavailable")
        action = str(args.get("action", "list")).lower()
        if action == "list":
            titles = [w.title for w in gw.getAllWindows() if (w.title or "").strip()]
            return ToolResult(success=True, data={"windows": titles}, verified=True)
        target = str(args.get("title", "")).lower()
        for w in gw.getAllWindows():
            if target and target in (w.title or "").lower():
                if action == "minimize":
                    w.minimize()
                elif action == "maximize":
                    w.maximize()
                else:
                    from .app_launcher import _focus_window
                    _focus_window(target)
                return ToolResult(success=True, data={"action": action, "title": w.title},
                                  verified=True)
        return ToolResult(success=False, error="no matching window")


class CaptureScreenTool(BaseTool):
    name = "capture_screen"
    description = "Take a full screenshot and save it to a temp file."
    risk_level = RiskLevel.LOW
    args_hint = ""

    async def execute(self, args: dict) -> ToolResult:
        try:
            import pyautogui
        except ImportError:
            return ToolResult(success=False, error="pyautogui unavailable")
        out = Path(tempfile.gettempdir()) / f"nirmiq_shot_{int(time.time())}.png"
        pyautogui.screenshot(str(out))
        return ToolResult(success=True, data={"path": str(out)}, verified=out.exists())


class CopyTextTool(BaseTool):
    name = "copy_text"
    description = "Copy text to the clipboard."
    risk_level = RiskLevel.SAFE
    args_hint = "text"

    def validate_args(self, args: dict) -> tuple[bool, str]:
        return ("text" in args, "text is required")

    async def execute(self, args: dict) -> ToolResult:
        import pyperclip
        pyperclip.copy(str(args["text"]))
        return ToolResult(success=True, data={"copied": True}, verified=True)


class PasteTextTool(BaseTool):
    name = "paste_text"
    description = "Type/paste text into the focused window."
    risk_level = RiskLevel.LOW
    args_hint = "text"

    def validate_args(self, args: dict) -> tuple[bool, str]:
        return ("text" in args, "text is required")

    async def execute(self, args: dict) -> ToolResult:
        import pyautogui
        import pyperclip
        pyperclip.copy(str(args["text"]))
        time.sleep(0.05)
        pyautogui.hotkey("ctrl", "v")
        return ToolResult(success=True, data={"pasted": True}, verified=True)
