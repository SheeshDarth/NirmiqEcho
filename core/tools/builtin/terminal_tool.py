"""terminal_executor — HIGH risk, requires confirmation, never sudo/admin."""
from __future__ import annotations

import asyncio

from core.shared.types import RiskLevel, ToolResult
from core.tools.base_tool import BaseTool

# Commands refused outright even with confirmation. Defence-in-depth: this
# tool is HIGH-risk and already requires explicit confirmation, but a
# blocklist of the most destructive / persistence / exfil patterns reduces
# blast radius if a user approves without reading carefully. Not a complete
# sandbox — confirmation is the primary control.
_BLOCKLIST = (
    "format ", "del /f", "del /q", "rmdir /s", "rd /s", "shutdown",
    "diskpart", "reg delete", "reg add", "sudo ", "runas", ":(){", "mkfs",
    "remove-item", "rm -rf", "rm -f", "vssadmin", "bcdedit", "cipher /w",
    "schtasks", "net user", "net localgroup", "wmic ", "fsutil",
    "invoke-webrequest", "invoke-expression", "iex", "downloadstring",
    "certutil -urlcache", "bitsadmin", "icacls", "takeown", "attrib ",
    "powershell -e", "-encodedcommand", "start-process", "new-service",
)


class TerminalExecutorTool(BaseTool):
    name = "terminal_executor"
    description = "Run a shell command (requires confirmation; refuses destructive ones)."
    risk_level = RiskLevel.HIGH
    args_hint = "command"

    def validate_args(self, args: dict) -> tuple[bool, str]:
        cmd = str(args.get("command", "")).strip()
        if not cmd:
            return False, "command is required"
        low = cmd.lower()
        if any(b in low for b in _BLOCKLIST):
            return False, "command is blocklisted for safety"
        return True, ""

    async def execute(self, args: dict) -> ToolResult:
        cmd = str(args["command"]).strip()
        try:
            proc = await asyncio.create_subprocess_shell(
                cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            out, err = await asyncio.wait_for(proc.communicate(), timeout=30)
        except asyncio.TimeoutError:
            return ToolResult(success=False, error="command timed out")
        text = (out or b"").decode(errors="replace")[-4000:]
        errtext = (err or b"").decode(errors="replace")[-2000:]
        ok = proc.returncode == 0
        return ToolResult(success=ok, verified=True,
                          data={"stdout": text, "returncode": proc.returncode},
                          error=None if ok else errtext or f"exit {proc.returncode}")
