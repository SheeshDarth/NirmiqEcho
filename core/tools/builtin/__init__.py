"""Aggregates every builtin tool instance."""
from __future__ import annotations

from core.tools.base_tool import BaseTool

from .app_launcher import OpenAppTool, CloseAppTool, FocusAppTool
from .browser_tools import OpenUrlTool, SearchWebTool
from .file_tools import (SearchFilesTool, CreateFileTool, MoveFileTool,
                         DeleteFileTool)
from .misc_tools import CalculateTool, LaunchProjectTool
from .note_tool import TakeNoteTool, ListNotesTool, SearchNotesTool
from .pdf_tool import PdfSummarizerTool
from .system_tools import (VolumeControlTool, WindowManagerTool,
                           CaptureScreenTool, CopyTextTool, PasteTextTool)
from .terminal_tool import TerminalExecutorTool
from .timer_tool import SetTimerTool


def all_builtin_tools(on_timer_fire=None, memory=None, router=None) -> list[BaseTool]:
    return [
        OpenAppTool(), CloseAppTool(), FocusAppTool(),
        SearchFilesTool(), CreateFileTool(), MoveFileTool(), DeleteFileTool(),
        OpenUrlTool(), SearchWebTool(),
        WindowManagerTool(), CaptureScreenTool(),
        CopyTextTool(), PasteTextTool(),
        VolumeControlTool(),
        TakeNoteTool(), ListNotesTool(), SearchNotesTool(),
        SetTimerTool(on_fire=on_timer_fire),
        TerminalExecutorTool(),
        CalculateTool(), LaunchProjectTool(memory=memory),
        PdfSummarizerTool(router=router),
    ]
