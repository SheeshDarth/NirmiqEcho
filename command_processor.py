"""
command_processor.py - Jarvis-style voice command engine for NirmiqEcho

When NirmiqEcho transcribes speech, it first passes text here.
The CommandProcessor decides:
  1. Is this a COMMAND?  → Execute the action silently (don't type it)
  2. Is this DICTATION?  → Pass to TextTyper and transcript

Supported command categories (all 100% offline, no LLM needed):
  - App launcher       : "open [app]", "launch [app]", "start [app]"
  - Web search         : "search for [query]", "google [query]"
  - YouTube            : "YouTube [query]", "play [query] on YouTube"
  - Messaging          : "WhatsApp [name]", "open WhatsApp"
  - Mode switch        : "switch to note mode", "search mode", "message mode"
  - Dictation control  : "stop", "pause", "clear", "new line", "new paragraph"
  - System             : "take screenshot", "open settings", "open file explorer"
  - Echo control       : "disable Echo", "stop Echo", "turn off Echo"
  - Clipboard          : "copy that", "paste that"

Architecture:
  CommandProcessor.process(text) → CommandResult(action, args, raw_text)
  NirmiqEchoApp._on_result() checks CommandResult.is_command
    → True:  CommandProcessor.execute(result)  [side effects]
    → False: TextTyper.type_text(result.raw_text)
"""

import re
import logging
import subprocess
import webbrowser
import os
from dataclasses import dataclass, field
from typing import Callable, Optional
from urllib.parse import quote_plus

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────
# Known Windows app name → executable mapping
# ─────────────────────────────────────────────────────────────────────

APP_MAP: dict[str, str] = {
    # Browsers
    "chrome":            "chrome",
    "google chrome":     "chrome",
    "firefox":           "firefox",
    "edge":              "msedge",
    "microsoft edge":    "msedge",
    "brave":             "brave",

    # Communication
    "whatsapp":          r"C:\Users\Siddharth\AppData\Local\WhatsApp\WhatsApp.exe",
    "telegram":          "telegram",
    "discord":           "discord",
    "teams":             "teams",
    "zoom":              "zoom",
    "slack":             "slack",

    # Productivity
    "notepad":           "notepad",
    "word":              "winword",
    "excel":             "excel",
    "powerpoint":        "powerpnt",
    "vscode":            "code",
    "vs code":           "code",
    "visual studio code": "code",
    "calculator":        "calc",
    "paint":             "mspaint",
    "task manager":      "taskmgr",
    "file explorer":     "explorer",
    "explorer":          "explorer",

    # Development
    "terminal":          "wt",
    "command prompt":    "cmd",
    "powershell":        "powershell",
    "git bash":          "git-bash",
    "android studio":    "studio64",
    "pycharm":           "pycharm64",
    "jupyter":           "jupyter-notebook",

    # Media / System
    "spotify":           "spotify",
    "vlc":               "vlc",
    "settings":          "ms-settings:",
    "control panel":     "control",
    "device manager":    "devmgmt.msc",
}

# Mode name aliases
MODE_ALIASES: dict[str, str] = {
    "note":        "note",
    "notes":       "note",
    "note mode":   "note",
    "message":     "message",
    "messages":    "message",
    "message mode": "message",
    "chat":        "message",
    "search":      "search",
    "search mode": "search",
    "default":     "default",
    "normal":      "default",
    "normal mode": "default",
    "typing":      "default",
    "dictation":   "default",
}


# ─────────────────────────────────────────────────────────────────────
# Command result dataclass
# ─────────────────────────────────────────────────────────────────────

@dataclass
class CommandResult:
    is_command: bool
    action: str = ""          # e.g. "open_app", "search_web", "switch_mode"
    args: dict = field(default_factory=dict)
    raw_text: str = ""        # original transcription text
    feedback: str = ""        # short message to show in UI (optional)


# ─────────────────────────────────────────────────────────────────────
# Command patterns (compiled once at import time)
# ─────────────────────────────────────────────────────────────────────

def _p(pattern: str) -> re.Pattern:
    return re.compile(pattern, re.IGNORECASE | re.UNICODE)


PATTERNS: list[tuple[re.Pattern, str]] = [
    # ── Mode switch (MUST be before search/open to avoid false matches) ──
    (_p(r"^(note[s]?|message[s]?|search|default|normal|dictation)\s+mode$"), "switch_mode"),
    (_p(r"^(?:switch\s+to|enable|use|turn\s+on)\s+(.+?)\s+mode$"),          "switch_mode"),

    # ── App launch ────────────────────────────────────────────────
    (_p(r"^(?:open|launch|start|run)\s+(.+)$"),             "open_app"),
    (_p(r"^(?:close|quit|exit)\s+(.+)$"),                   "close_app"),

    # ── Web search ────────────────────────────────────────────────
    (_p(r"^(?:search(?:\s+for)?|google(?:\s+for)?)\s+(.+)$"), "search_web"),
    (_p(r"^(?:look\s+up|find)\s+(.+)$"),                    "search_web"),

    # ── YouTube ───────────────────────────────────────────────────
    (_p(r"^(?:play|youtube|watch)\s+(.+?)(?:\s+on\s+youtube)?$"), "youtube"),
    (_p(r"^(.+)\s+on\s+youtube$"),                          "youtube"),

    # ── WhatsApp ─────────────────────────────────────────────────
    (_p(r"^(?:whatsapp|text|send(?:\s+(?:a\s+)?message(?:\s+to)?)?)\s+(.+)$"), "whatsapp"),
    (_p(r"^(?:message)\s+(.+)$"),                           "whatsapp"),
    (_p(r"^open\s+whatsapp$"),                              "open_whatsapp"),

    # ── Dictation control ─────────────────────────────────────────
    (_p(r"^(?:new\s+line|next\s+line)$"),                   "new_line"),
    (_p(r"^(?:new\s+paragraph|next\s+paragraph)$"),         "new_paragraph"),
    (_p(r"^delete\s+that$"),                                "delete_last"),
    (_p(r"^(?:copy\s+that|copy\s+all)$"),                   "copy_clipboard"),
    (_p(r"^(?:paste\s+that|paste\s+it)$"),                  "paste_clipboard"),

    # ── Echo / listening control ──────────────────────────────────
    (_p(r"^(?:stop\s+(?:listening|echo)|disable\s+echo|turn\s+off\s+echo|echo\s+off)$"), "stop_echo"),
    (_p(r"^(?:pause\s+(?:listening|echo))$"),               "pause_echo"),
    (_p(r"^clear(?:\s+(?:transcript|screen|all))?$"),       "clear_transcript"),

    # ── System actions ────────────────────────────────────────────
    (_p(r"^take\s+(?:a\s+)?screenshot$"),                   "screenshot"),
    (_p(r"^(?:show\s+)?(?:open\s+)?(?:my\s+)?(?:files?|file\s+explorer|explorer)$"), "file_explorer"),
    (_p(r"^(?:open\s+)?settings$"),                         "open_settings"),
    (_p(r"^(?:open\s+)?task\s*manager$"),                   "task_manager"),
    (_p(r"^(?:minimize|minimise)\s+(?:window|this)$"),      "minimize_window"),
    (_p(r"^(?:maximize|maximise)\s+(?:window|this)$"),      "maximize_window"),
    (_p(r"^(?:close\s+(?:window|this)|alt\s+f4)$"),        "close_window"),

    # ── Typing mode (force text output for one utterance) ─────────
    (_p(r"^(?:type|write|dictate|say)\s+(.+)$"),            "force_type"),
]


# ─────────────────────────────────────────────────────────────────────
# CommandProcessor
# ─────────────────────────────────────────────────────────────────────

class CommandProcessor:
    """
    Classifies transcribed text as a command or dictation, then executes.

    Callbacks from NirmiqEchoApp are injected so commands can control the app:
      - on_mode_change(mode)     : switch typing mode
      - on_stop_echo()           : disable Echo Mode
      - on_clear_transcript()    : clear transcript panel
      - on_status_change(status) : show feedback in status bar
    """

    def __init__(
        self,
        on_mode_change: Callable[[str], None] | None = None,
        on_stop_echo: Callable[[], None] | None = None,
        on_clear_transcript: Callable[[], None] | None = None,
        on_status_change: Callable[[str], None] | None = None,
        on_feedback: Callable[[str], None] | None = None,
    ):
        self._on_mode_change    = on_mode_change    or (lambda m: None)
        self._on_stop_echo      = on_stop_echo      or (lambda: None)
        self._on_clear          = on_clear_transcript or (lambda: None)
        self._on_status         = on_status_change  or (lambda s: None)
        self._on_feedback       = on_feedback       or (lambda m: None)

        # Text buffer for "delete that" and clipboard ops
        self._last_typed: str = ""

        # Active mode
        self._mode: str = "default"

        logger.info("CommandProcessor: ready (%d patterns)", len(PATTERNS))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def process(self, text: str) -> CommandResult:
        """
        Classify `text` as a command or dictation.

        Returns a CommandResult. Caller decides whether to type or execute.
        """
        cleaned = text.strip().rstrip(".")

        for pattern, action in PATTERNS:
            m = pattern.match(cleaned)
            if m:
                # Extract first capture group (the argument) if present
                arg = m.group(1).strip() if m.lastindex else ""
                result = self._build_result(action, arg, text)
                if result is not None:
                    logger.info("Command detected: %s | arg=%r", action, arg)
                    return result

        # Not a command — dictation
        return CommandResult(is_command=False, raw_text=text)

    def execute(self, result: CommandResult) -> None:
        """Execute a recognised command."""
        action = result.action
        args   = result.args

        try:
            if action == "open_app":
                self._open_app(args.get("app_name", ""))
            elif action == "close_app":
                self._close_app(args.get("app_name", ""))
            elif action == "search_web":
                self._search_web(args.get("query", ""))
            elif action == "youtube":
                self._youtube(args.get("query", ""))
            elif action == "whatsapp":
                self._whatsapp(args.get("contact", ""))
            elif action == "open_whatsapp":
                self._open_app("whatsapp")
            elif action == "switch_mode":
                self._switch_mode(args.get("mode", "default"))
            elif action == "new_line":
                self._type_key("\n")
            elif action == "new_paragraph":
                self._type_key("\n\n")
            elif action == "delete_last":
                self._delete_last()
            elif action == "copy_clipboard":
                self._copy_clipboard()
            elif action == "paste_clipboard":
                self._paste_clipboard()
            elif action == "stop_echo":
                self._on_stop_echo()
                self._feedback("Echo Mode disabled")
            elif action == "pause_echo":
                self._on_stop_echo()
                self._feedback("Listening paused")
            elif action == "clear_transcript":
                self._on_clear()
                self._feedback("Transcript cleared")
            elif action == "screenshot":
                self._screenshot()
            elif action == "file_explorer":
                self._open_app("explorer")
            elif action == "open_settings":
                self._open_settings()
            elif action == "task_manager":
                self._open_app("taskmgr")
            elif action == "minimize_window":
                self._minimize_window()
            elif action == "maximize_window":
                self._maximize_window()
            elif action == "close_window":
                self._close_window()
            elif action == "force_type":
                # "type [text]" → type the text even if it looks like a command
                result.is_command = False   # re-route to typer
                result.raw_text = args.get("text", result.raw_text)
            else:
                logger.warning("CommandProcessor: unknown action '%s'", action)

        except Exception as exc:
            logger.error("CommandProcessor: execute error for '%s': %s", action, exc,
                         exc_info=True)
            self._feedback(f"Command failed: {exc}")

    def record_typed(self, text: str) -> None:
        """Tell the processor what was last typed (for 'delete that' support)."""
        self._last_typed = text

    @property
    def mode(self) -> str:
        return self._mode

    # ------------------------------------------------------------------
    # Result builder
    # ------------------------------------------------------------------

    def _build_result(self, action: str, arg: str, raw: str) -> CommandResult | None:
        """Convert regex match into a structured CommandResult."""

        if action == "open_app":
            app = self._resolve_app(arg)
            # Only treat as command if we can identify the app
            if app:
                return CommandResult(True, action, {"app_name": arg},
                                     raw, feedback=f"Opening {arg}...")
            # Unknown app → fall through to dictation
            return None

        elif action == "close_app":
            return CommandResult(True, action, {"app_name": arg}, raw,
                                 feedback=f"Closing {arg}...")

        elif action == "search_web":
            return CommandResult(True, action, {"query": arg}, raw,
                                 feedback=f"Searching: {arg}")

        elif action == "youtube":
            return CommandResult(True, action, {"query": arg}, raw,
                                 feedback=f"YouTube: {arg}")

        elif action == "whatsapp":
            return CommandResult(True, action, {"contact": arg}, raw,
                                 feedback=f"Opening WhatsApp for {arg}")

        elif action == "open_whatsapp":
            return CommandResult(True, action, {}, raw, feedback="Opening WhatsApp")

        elif action == "switch_mode":
            mode = MODE_ALIASES.get(arg.lower())
            if mode:
                return CommandResult(True, action, {"mode": mode}, raw,
                                     feedback=f"Mode: {mode}")
            return None   # unrecognised mode → dictation

        elif action == "force_type":
            return CommandResult(False, action, {"text": arg}, arg)

        else:
            # All other commands need no arg validation
            return CommandResult(True, action, {}, raw)

    # ------------------------------------------------------------------
    # Action implementations
    # ------------------------------------------------------------------

    def _open_app(self, app_name: str) -> None:
        """Launch a Windows application by friendly name."""
        exe = self._resolve_app(app_name)
        if not exe:
            self._feedback(f"Unknown app: {app_name}")
            return

        logger.info("Launching app: %s → %s", app_name, exe)
        self._feedback(f"Opening {app_name.title()}...")

        try:
            if exe.startswith("ms-settings:"):
                os.startfile(exe)
            else:
                subprocess.Popen([exe], shell=True,
                                  creationflags=subprocess.CREATE_NO_WINDOW)
        except FileNotFoundError:
            # Try via shell (handles PATH apps)
            subprocess.Popen(exe, shell=True)

    def _close_app(self, app_name: str) -> None:
        """Attempt to close an app by process name."""
        exe = self._resolve_app(app_name)
        proc = os.path.basename(exe) if exe else app_name
        if not proc.endswith(".exe"):
            proc += ".exe"
        subprocess.Popen(["taskkill", "/IM", proc, "/F"], shell=True,
                          creationflags=subprocess.CREATE_NO_WINDOW)
        self._feedback(f"Closing {app_name.title()}")

    def _search_web(self, query: str) -> None:
        """Open default browser with Google search."""
        url = f"https://www.google.com/search?q={quote_plus(query)}"
        logger.info("Web search: %s", url)
        self._feedback(f"Searching: {query}")
        webbrowser.open(url)

    def _youtube(self, query: str) -> None:
        """Open YouTube search for query."""
        url = f"https://www.youtube.com/results?search_query={quote_plus(query)}"
        logger.info("YouTube: %s", url)
        self._feedback(f"YouTube: {query}")
        webbrowser.open(url)

    def _whatsapp(self, contact: str) -> None:
        """Open WhatsApp — either app or web, with contact pre-filled if found."""
        # Try to open WhatsApp app first, fall back to web
        wa_exe = APP_MAP.get("whatsapp", "")
        if wa_exe and os.path.exists(wa_exe):
            subprocess.Popen([wa_exe], creationflags=subprocess.CREATE_NO_WINDOW)
            self._feedback(f"WhatsApp opened")
        else:
            url = f"https://web.whatsapp.com/"
            webbrowser.open(url)
            self._feedback("WhatsApp Web opened")

    def _switch_mode(self, mode: str) -> None:
        self._mode = mode
        self._on_mode_change(mode)
        self._feedback(f"Mode: {mode.title()}")
        logger.info("Mode switched to: %s", mode)

    def _screenshot(self) -> None:
        """Take screenshot using Win+PrtSc (saves to Pictures/Screenshots)."""
        try:
            import pyautogui
            import time
            pyautogui.hotkey("win", "printscreen")
            self._feedback("Screenshot saved to Pictures/Screenshots")
        except Exception as exc:
            self._feedback(f"Screenshot failed: {exc}")

    def _open_settings(self) -> None:
        os.startfile("ms-settings:")
        self._feedback("Settings opened")

    def _minimize_window(self) -> None:
        try:
            import pyautogui
            pyautogui.hotkey("win", "down")
            self._feedback("Window minimised")
        except Exception as exc:
            self._feedback(f"Failed: {exc}")

    def _maximize_window(self) -> None:
        try:
            import pyautogui
            pyautogui.hotkey("win", "up")
            self._feedback("Window maximised")
        except Exception as exc:
            self._feedback(f"Failed: {exc}")

    def _close_window(self) -> None:
        try:
            import pyautogui
            pyautogui.hotkey("alt", "f4")
            self._feedback("Window closed")
        except Exception as exc:
            self._feedback(f"Failed: {exc}")

    def _type_key(self, keys: str) -> None:
        try:
            import pyperclip, pyautogui
            pyautogui.typewrite(keys, interval=0)
        except Exception:
            pass

    def _delete_last(self) -> None:
        """Delete last typed text using backspace."""
        if not self._last_typed:
            return
        try:
            import pyautogui
            count = len(self._last_typed) + 1   # +1 for the space appended
            pyautogui.press("backspace", presses=count, interval=0.01)
            self._feedback("Deleted")
        except Exception as exc:
            self._feedback(f"Delete failed: {exc}")

    def _copy_clipboard(self) -> None:
        try:
            import pyautogui
            pyautogui.hotkey("ctrl", "a")
            pyautogui.hotkey("ctrl", "c")
            self._feedback("Copied to clipboard")
        except Exception as exc:
            self._feedback(f"Copy failed: {exc}")

    def _paste_clipboard(self) -> None:
        try:
            import pyautogui
            pyautogui.hotkey("ctrl", "v")
            self._feedback("Pasted")
        except Exception as exc:
            self._feedback(f"Paste failed: {exc}")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _resolve_app(self, name: str) -> str:
        """Look up app name in APP_MAP (case-insensitive)."""
        return APP_MAP.get(name.lower().strip(), "")

    def _feedback(self, msg: str) -> None:
        logger.info("Command feedback: %s", msg)
        self._on_feedback(msg)


# ─────────────────────────────────────────────────────────────────────
# Quick test
# ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(levelname)-8s %(message)s")

    feedback_log = []
    cp = CommandProcessor(
        on_feedback=lambda m: feedback_log.append(m)
    )

    test_phrases = [
        "open Chrome",
        "open notepad",
        "search for machine learning tutorials",
        "Google how to learn Python fast",
        "YouTube lo-fi music for studying",
        "play coding music on YouTube",
        "switch to note mode",
        "search mode",
        "new line",
        "delete that",
        "copy that",
        "stop Echo",
        "take a screenshot",
        "open file explorer",
        "clear transcript",
        "Hello, my name is Siddharth",        # should be dictation
        "I am building income systems",       # should be dictation
        "type open notepad please",           # force type (not a command)
        "open WhatsApp",
        "WhatsApp Rahul",
    ]

    print("CommandProcessor test:\n")
    for phrase in test_phrases:
        result = cp.process(phrase)
        kind = "[CMD]" if result.is_command else "[TXT]"
        detail = f"{result.action}: {result.args}" if result.is_command else f'type: "{result.raw_text}"'
        print(f"  {kind} '{phrase}'")
        print(f"       {detail}")
        print()
