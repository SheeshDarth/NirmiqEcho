"""App control tools: open_app, close_app, focus_app."""
from __future__ import annotations

import os
import re
import shutil
import subprocess

from core.shared.types import RiskLevel, ToolResult
from core.tools.base_tool import BaseTool

_NO_WINDOW = 0x08000000  # CREATE_NO_WINDOW
_SAFE = re.compile(r"^[\w.+\- ()]+$")
# Only these URI schemes may be handed to os.startfile. Prevents a voice/LLM
# string like "javascript:..." or "file:///..." from invoking an arbitrary
# protocol handler.
_ALLOWED_SCHEMES = ("http:", "https:", "ms-", "spotify:", "whatsapp:",
                    "outlookcal:", "bingmaps:", "ms-settings:")

# Friendly name -> launch target (bare exe, protocol URI, or path)
APP_MAP = {
    "chrome": "chrome", "google chrome": "chrome", "firefox": "firefox",
    "edge": "msedge", "brave": "brave", "notepad": "notepad",
    "calculator": "calc", "vscode": "code", "vs code": "code",
    "code": "code", "explorer": "explorer", "file explorer": "explorer",
    "spotify": "spotify:", "whatsapp": "whatsapp:", "terminal": "wt",
    "settings": "ms-settings:", "task manager": "taskmgr", "paint": "mspaint",
    "cmd": "cmd", "powershell": "powershell",
}

PROC_MAP = {
    "chrome": "chrome.exe", "firefox": "firefox.exe", "edge": "msedge.exe",
    "brave": "brave.exe", "spotify": "Spotify.exe", "whatsapp": "WhatsApp.exe",
    "notepad": "notepad.exe", "calculator": "Calculator.exe", "code": "Code.exe",
    "vscode": "Code.exe", "explorer": "explorer.exe",
}


def _launch(target: str) -> None:
    target = target.strip()
    low = target.lower()
    if low.startswith(("http://", "https://")):
        import webbrowser
        webbrowser.open(target)
        return
    # A URI scheme (scheme:...), but NOT a Windows drive path (C:\...).
    is_uri = bool(re.match(r"^[A-Za-z][\w+.-]*:", target)) and \
        not re.match(r"^[A-Za-z]:[\\/]", target)
    if is_uri:
        if not low.startswith(_ALLOWED_SCHEMES):
            raise ValueError(f"disallowed URI scheme: {target!r}")
        os.startfile(target)
        return
    if low.endswith(".lnk") or os.path.isfile(target):
        os.startfile(target)
        return
    # Bare command name — must be benign and contain no scheme/path chars.
    if not _SAFE.match(target) or ":" in target:
        raise ValueError(f"unsafe launch target: {target!r}")
    resolved = shutil.which(target.split()[0])
    if resolved:
        subprocess.Popen([resolved, *target.split()[1:]], shell=False,
                         creationflags=_NO_WINDOW)
    else:
        os.startfile(target if low.endswith(".exe") else target + ".exe")


class OpenAppTool(BaseTool):
    name = "open_app"
    description = "Launch an application by name (or focus it if already running)."
    risk_level = RiskLevel.LOW
    args_hint = "app_name"

    def validate_args(self, args: dict) -> tuple[bool, str]:
        return (bool(args.get("app_name")), "app_name is required")

    async def execute(self, args: dict) -> ToolResult:
        name = str(args["app_name"]).lower().strip()
        target = APP_MAP.get(name, name.split()[0] if name else "")
        if not target:
            return ToolResult(success=False, error="No app name given")
        _launch(target)
        return ToolResult(success=True, data={"launched": name}, verified=True)


class CloseAppTool(BaseTool):
    name = "close_app"
    description = "Close a running application gracefully."
    risk_level = RiskLevel.MEDIUM
    args_hint = "app_name"

    def validate_args(self, args: dict) -> tuple[bool, str]:
        return (bool(args.get("app_name")), "app_name is required")

    async def execute(self, args: dict) -> ToolResult:
        name = str(args["app_name"]).lower().strip()
        proc = PROC_MAP.get(name, name.split()[0] + ".exe")
        if not re.match(r"^[\w.+\- ()]+\.exe$", proc, re.IGNORECASE):
            return ToolResult(success=False, error=f"unsafe process name: {proc}")
        killed = False
        try:
            import psutil
            stem = proc.lower().removesuffix(".exe")
            for p in psutil.process_iter(["name"]):
                if (p.info["name"] or "").lower().removesuffix(".exe") == stem:
                    p.terminate()
                    killed = True
        except Exception:
            subprocess.Popen(["taskkill", "/IM", proc, "/F"], shell=False,
                             creationflags=_NO_WINDOW)
            killed = True
        return ToolResult(success=killed, data={"closed": proc}, verified=killed,
                          error=None if killed else "process not found")


class FocusAppTool(BaseTool):
    name = "focus_app"
    description = "Bring an application window to the foreground."
    risk_level = RiskLevel.LOW
    args_hint = "app_name"

    def validate_args(self, args: dict) -> tuple[bool, str]:
        return (bool(args.get("app_name")), "app_name is required")

    async def execute(self, args: dict) -> ToolResult:
        name = str(args["app_name"]).lower().strip()
        ok = _focus_window(name)
        if not ok:
            _launch(APP_MAP.get(name, name.split()[0]))
            return ToolResult(success=True, data={"launched": name}, verified=False)
        return ToolResult(success=True, data={"focused": name}, verified=True)


def _focus_window(title_substring: str, timeout: float = 4.0) -> bool:
    """Foreground a window, defeating the Windows foreground-lock (Alt tap)."""
    import time
    try:
        import ctypes
        import pygetwindow as gw
    except Exception:
        return False
    user32 = ctypes.windll.user32
    needle = title_substring.lower()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for w in gw.getAllWindows():
            if needle in (w.title or "").lower() and w.visible:
                hwnd = getattr(w, "_hWnd", None)
                if not hwnd:
                    continue
                user32.ShowWindow(hwnd, 9)
                user32.keybd_event(0x12, 0, 0, 0)
                user32.SetForegroundWindow(hwnd)
                user32.keybd_event(0x12, 0, 2, 0)
                time.sleep(0.3)
                if user32.GetForegroundWindow() == hwnd:
                    return True
        time.sleep(0.2)
    return False
