"""
command_processor.py - Jarvis-style voice command engine for NirmiqEcho

Complete personal assistant — 100% offline, no LLM needed.

Command categories:
  App control      : open/close/switch to any installed app
  Music            : play [song], pause, next, previous, volume
  Navigation       : go back, forward, refresh, new tab, scroll
  Web              : search, Google, YouTube
  Messaging        : WhatsApp, Telegram
  System           : screenshot, volume, brightness, shutdown, restart
  Dictation        : new line, delete that, copy, paste, type [text]
  Time / Info      : what time is it, set timer, date
  Echo control     : stop Echo, disable Echo
  Window control   : minimize, maximize, close window, switch window

Flow:
  CommandProcessor.process(text) → CommandResult
  → is_command=True  : execute silently, show feedback
  → is_command=False : type text into focused app
"""

import re
import logging
import subprocess
import webbrowser
import os
import threading
import time
import datetime
from dataclasses import dataclass, field
from typing import Callable
from urllib.parse import quote_plus
from pathlib import Path

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────
# Command result
# ─────────────────────────────────────────────────────────────────────

@dataclass
class CommandResult:
    is_command: bool
    action:     str  = ""
    args:       dict = field(default_factory=dict)
    raw_text:   str  = ""
    feedback:   str  = ""


# ─────────────────────────────────────────────────────────────────────
# Pattern compiler helper
# ─────────────────────────────────────────────────────────────────────

def _p(pattern: str) -> re.Pattern:
    return re.compile(pattern, re.IGNORECASE | re.UNICODE)


# ─────────────────────────────────────────────────────────────────────
# Command patterns  (order = priority)
# ─────────────────────────────────────────────────────────────────────

PATTERNS: list[tuple[re.Pattern, str]] = [

    # ── Mode switch (before search/open to avoid false positives) ────
    (_p(r"^(note[s]?|message[s]?|search|default|normal|dictation|typing)\s+mode$"),
                                                             "switch_mode"),
    (_p(r"^(?:switch\s+to|enable|use|turn\s+on)\s+(.+?)\s+mode$"),
                                                             "switch_mode"),

    # ── Time / date queries ──────────────────────────────────────────
    (_p(r"^what(?:'s|\s+is)?\s+(?:the\s+)?(?:time|current\s+time)(?:\s+is\s+it)?[\?]?$"),
                                                             "tell_time"),
    (_p(r"^(?:tell\s+me\s+(?:the\s+)?)?(?:current\s+)?time[\?]?$"),
                                                             "tell_time"),
    (_p(r"^what(?:'s|\s+is)?\s+(?:the\s+)?(?:date|today(?:'s\s+date)?)(?:\s+is\s+it)?[\?]?$"),
                                                             "tell_date"),
    (_p(r"^(?:what\s+)?(?:day\s+is\s+(?:it|today)|today(?:'s\s+day)?)[\?]?$"),
                                                             "tell_date"),

    # ── Timer ────────────────────────────────────────────────────────
    (_p(r"^set\s+(?:a\s+)?timer\s+(?:for\s+)?(\d+)\s*(minute[s]?|min[s]?|second[s]?|sec[s]?|hour[s]?|hr[s]?)$"),
                                                             "set_timer"),
    (_p(r"^(?:remind\s+me\s+in)\s+(\d+)\s*(minute[s]?|min[s]?|second[s]?|hour[s]?|hr[s]?)$"),
                                                             "set_timer"),

    # ── Music control ────────────────────────────────────────────────
    (_p(r"^(?:play|put\s+on|listen\s+to)\s+(.+?)(?:\s+(?:song|music|track|on\s+spotify|on\s+youtube))?$"),
                                                             "play_music"),
    (_p(r"^(?:pause|stop)\s+(?:music|song|spotify|playing)$"),
                                                             "pause_music"),
    (_p(r"^(?:resume|continue)\s+(?:music|song|playing)$"), "resume_music"),
    (_p(r"^(?:next|skip)(?:\s+(?:song|track|music))?$"),    "next_track"),
    (_p(r"^(?:previous|prev|last)(?:\s+(?:song|track|music))?$"),
                                                             "prev_track"),
    (_p(r"^(?:volume\s+up|louder|increase\s+volume)$"),     "volume_up"),
    (_p(r"^(?:volume\s+down|quieter|lower\s+volume|decrease\s+volume)$"),
                                                             "volume_down"),
    (_p(r"^(?:mute|unmute)(?:\s+(?:volume|sound))?$"),      "toggle_mute"),
    (_p(r"^set\s+volume\s+(?:to\s+)?(\d{1,3})(?:\s*percent)?$"),
                                                             "set_volume"),

    # ── Navigation ───────────────────────────────────────────────────
    (_p(r"^(?:go\s+)?back(?:\s+(?:button|page))?$"),        "nav_back"),
    (_p(r"^(?:go\s+)?forward(?:\s+(?:button|page))?$"),     "nav_forward"),
    (_p(r"^(?:refresh|reload)(?:\s+(?:page|tab))?$"),       "nav_refresh"),
    (_p(r"^(?:new\s+tab|open\s+(?:a\s+)?new\s+tab)$"),      "new_tab"),
    (_p(r"^(?:close\s+tab|close\s+this\s+tab)$"),           "close_tab"),
    (_p(r"^(?:next\s+tab|switch\s+tab)$"),                  "next_tab"),
    (_p(r"^(?:scroll\s+(?:up|down)|page\s+(?:up|down))$"),  "scroll"),
    (_p(r"^scroll\s+(up|down)(?:\s+(\d+))?$"),              "scroll"),
    (_p(r"^(?:page\s+up|scroll\s+top|go\s+to\s+top)$"),    "scroll_top"),
    (_p(r"^(?:page\s+down|scroll\s+bottom|go\s+to\s+bottom)$"),
                                                             "scroll_bottom"),
    (_p(r"^(?:switch\s+window|alt\s+tab|next\s+window)$"),  "switch_window"),
    (_p(r"^(?:zoom\s+in|increase\s+zoom)$"),                "zoom_in"),
    (_p(r"^(?:zoom\s+out|decrease\s+zoom)$"),               "zoom_out"),

    # ── Window control ───────────────────────────────────────────────
    (_p(r"^(?:minimize|minimise)(?:\s+(?:window|this))?$"), "minimize_window"),
    (_p(r"^(?:maximize|maximise)(?:\s+(?:window|this))?$"), "maximize_window"),
    (_p(r"^(?:close\s+(?:window|this)|alt\s+f4)$"),         "close_window"),
    (_p(r"^(?:restore\s+window|show\s+window)$"),           "restore_window"),
    (_p(r"^show\s+desktop$"),                               "show_desktop"),

    # ── URL open (before open_app to catch domain names) ────────────
    (_p(r"^(?:open|go\s+to)\s+(https?://.+)$"),             "open_url"),
    (_p(r"^(?:go\s+to|open|visit)\s+(\S+\.(?:com|org|net|io|in|co|dev|app))(?:/\S*)?$"),
                                                             "open_url"),

    # ── App launch ───────────────────────────────────────────────────
    (_p(r"^(?:open|launch|start|run)\s+(.+)$"),             "open_app"),

    # ── App close ────────────────────────────────────────────────────
    (_p(r"^(?:close|quit|exit|kill|shut\s+down)\s+(.+)$"),  "close_app"),

    # ── Web search ───────────────────────────────────────────────────
    (_p(r"^(?:search(?:\s+for)?|google(?:\s+for)?)\s+(.+)$"), "search_web"),
    (_p(r"^(?:look\s+up|find|what\s+is|who\s+is|how\s+(?:to|do))\s+(.+)$"),
                                                             "search_web"),
    (_p(r"^(?:open|go\s+to)\s+(https?://.+)$"),             "open_url"),
    (_p(r"^(?:go\s+to|open|visit)\s+(.+\.(?:com|org|net|io|in|co))(?:/.*)?$"),
                                                             "open_url"),

    # ── YouTube ──────────────────────────────────────────────────────
    (_p(r"^(?:youtube|watch|play\s+on\s+youtube)\s+(.+)$"), "youtube"),
    (_p(r"^(.+)\s+on\s+youtube$"),                          "youtube"),

    # ── WhatsApp ─────────────────────────────────────────────────────
    (_p(r"^open\s+whatsapp$"),                              "open_whatsapp"),
    (_p(r"^(?:whatsapp|text|message)\s+(.+)$"),             "whatsapp"),

    # ── Dictation control ────────────────────────────────────────────
    (_p(r"^(?:new\s+line|press\s+enter|next\s+line)$"),     "new_line"),
    (_p(r"^(?:new\s+paragraph|double\s+enter)$"),           "new_paragraph"),
    (_p(r"^(?:tab|press\s+tab)$"),                          "press_tab"),
    (_p(r"^delete\s+(?:that|last|it)$"),                    "delete_last"),
    (_p(r"^(?:copy\s+that|copy\s+all|ctrl\s+c)$"),          "copy_clipboard"),
    (_p(r"^(?:paste\s+that|paste\s+it|ctrl\s+v)$"),         "paste_clipboard"),
    (_p(r"^(?:undo|ctrl\s+z)$"),                            "undo"),
    (_p(r"^(?:redo|ctrl\s+y)$"),                            "redo"),
    (_p(r"^select\s+all$"),                                  "select_all"),

    # ── Echo / listening control ─────────────────────────────────────
    (_p(r"^(?:stop|disable|turn\s+off)\s+(?:echo|listening)$"),
                                                             "stop_echo"),
    (_p(r"^echo\s+off$"),                                   "stop_echo"),
    (_p(r"^(?:pause\s+(?:listening|echo))$"),               "pause_echo"),
    (_p(r"^clear(?:\s+(?:transcript|screen|all))?$"),       "clear_transcript"),

    # ── System ───────────────────────────────────────────────────────
    (_p(r"^take\s+(?:a\s+)?screenshot$"),                   "screenshot"),
    (_p(r"^(?:open\s+)?settings$"),                         "open_settings"),
    (_p(r"^(?:open\s+)?(?:file\s+)?explorer$"),             "file_explorer"),
    (_p(r"^(?:open\s+)?task\s*manager$"),                   "task_manager"),
    (_p(r"^(?:lock|lock\s+(?:screen|computer|pc))$"),       "lock_screen"),
    (_p(r"^(?:sleep|sleep\s+(?:mode|computer|pc))$"),       "sleep"),
    (_p(r"^(?:shutdown|shut\s+down|turn\s+off)(?:\s+(?:computer|pc))?$"),
                                                             "shutdown"),
    (_p(r"^(?:restart|reboot)(?:\s+(?:computer|pc))?$"),    "restart"),
    (_p(r"^(?:brightness\s+up|increase\s+brightness)$"),    "brightness_up"),
    (_p(r"^(?:brightness\s+down|decrease\s+brightness)$"),  "brightness_down"),

    # ── Typing mode (force text even if it looks like a command) ─────
    (_p(r"^(?:type|write|dictate|say)\s+(.+)$"),            "force_type"),
]

MODE_ALIASES: dict[str, str] = {
    "note": "note", "notes": "note", "note mode": "note",
    "message": "message", "messages": "message", "chat": "message",
    "search": "search", "search mode": "search",
    "default": "default", "normal": "default", "typing": "default",
    "dictation": "default",
}


# ─────────────────────────────────────────────────────────────────────
# CommandProcessor
# ─────────────────────────────────────────────────────────────────────

class CommandProcessor:
    """
    Classifies and executes voice commands. Works 100% offline.
    """

    def __init__(
        self,
        on_mode_change:      Callable[[str], None] | None = None,
        on_stop_echo:        Callable[[], None]     | None = None,
        on_clear_transcript: Callable[[], None]     | None = None,
        on_status_change:    Callable[[str], None]  | None = None,
        on_feedback:         Callable[[str], None]  | None = None,
    ):
        self._on_mode_change = on_mode_change    or (lambda m: None)
        self._on_stop_echo   = on_stop_echo      or (lambda: None)
        self._on_clear       = on_clear_transcript or (lambda: None)
        self._on_status      = on_status_change  or (lambda s: None)
        self._on_feedback    = on_feedback       or (lambda m: None)

        self._last_typed = ""
        self._mode       = "default"
        self._timers: list[threading.Timer] = []

        # Lazy-load app discovery (registry scan runs in background)
        self._discovery = None
        threading.Thread(target=self._init_discovery, daemon=True).start()

        logger.info("CommandProcessor: ready (%d patterns)", len(PATTERNS))

    def _init_discovery(self):
        from app_discovery import get_discovery
        self._discovery = get_discovery()
        self._discovery._build_cache()   # pre-warm cache

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def process(self, text: str) -> CommandResult:
        """Classify text as command or dictation."""
        cleaned = text.strip().rstrip(".")

        for pattern, action in PATTERNS:
            m = pattern.match(cleaned)
            if m:
                arg = m.group(1).strip() if m.lastindex else ""
                result = self._build_result(action, arg, text, m)
                if result is not None:
                    logger.info("Command: %s | %r", action, arg)
                    return result

        return CommandResult(is_command=False, raw_text=text)

    def execute(self, result: CommandResult) -> None:
        """Execute a recognised command."""
        a = result.action
        g = result.args

        dispatch = {
            "open_app":        lambda: self._open_app(g.get("app_name", "")),
            "close_app":       lambda: self._close_app(g.get("app_name", "")),
            "play_music":      lambda: self._play_music(g.get("query", "")),
            "pause_music":     lambda: self._media_key("playpause"),
            "resume_music":    lambda: self._media_key("playpause"),
            "next_track":      lambda: self._media_key("nexttrack"),
            "prev_track":      lambda: self._media_key("prevtrack"),
            "volume_up":       lambda: self._volume_change(+2),
            "volume_down":     lambda: self._volume_change(-2),
            "toggle_mute":     lambda: self._media_key("volumemute"),
            "set_volume":      lambda: self._set_volume(int(g.get("level", 50))),
            "search_web":      lambda: self._search_web(g.get("query", "")),
            "open_url":        lambda: self._open_url(g.get("url", "")),
            "youtube":         lambda: self._youtube(g.get("query", "")),
            "whatsapp":        lambda: self._whatsapp(g.get("contact", "")),
            "open_whatsapp":   lambda: self._open_app("whatsapp"),
            "switch_mode":     lambda: self._switch_mode(g.get("mode", "default")),
            "tell_time":       lambda: self._tell_time(),
            "tell_date":       lambda: self._tell_date(),
            "set_timer":       lambda: self._set_timer(int(g.get("amount", 1)),
                                                       g.get("unit", "min")),
            "nav_back":        lambda: self._hotkey("alt", "left"),
            "nav_forward":     lambda: self._hotkey("alt", "right"),
            "nav_refresh":     lambda: self._hotkey("f5"),
            "new_tab":         lambda: self._hotkey("ctrl", "t"),
            "close_tab":       lambda: self._hotkey("ctrl", "w"),
            "next_tab":        lambda: self._hotkey("ctrl", "tab"),
            "scroll":          lambda: self._scroll(g.get("direction", "down"),
                                                    int(g.get("amount", 3))),
            "scroll_top":      lambda: self._hotkey("ctrl", "home"),
            "scroll_bottom":   lambda: self._hotkey("ctrl", "end"),
            "switch_window":   lambda: self._hotkey("alt", "tab"),
            "zoom_in":         lambda: self._hotkey("ctrl", "+"),
            "zoom_out":        lambda: self._hotkey("ctrl", "-"),
            "new_line":        lambda: self._press("enter"),
            "new_paragraph":   lambda: [self._press("enter"), self._press("enter")],
            "press_tab":       lambda: self._press("tab"),
            "delete_last":     lambda: self._delete_last(),
            "copy_clipboard":  lambda: self._hotkey("ctrl", "c"),
            "paste_clipboard": lambda: self._hotkey("ctrl", "v"),
            "undo":            lambda: self._hotkey("ctrl", "z"),
            "redo":            lambda: self._hotkey("ctrl", "y"),
            "select_all":      lambda: self._hotkey("ctrl", "a"),
            "minimize_window": lambda: self._hotkey("win", "down"),
            "maximize_window": lambda: self._hotkey("win", "up"),
            "close_window":    lambda: self._hotkey("alt", "f4"),
            "restore_window":  lambda: self._hotkey("win", "up"),
            "show_desktop":    lambda: self._hotkey("win", "d"),
            "stop_echo":       lambda: [self._on_stop_echo(),
                                        self._feedback("Echo off")],
            "pause_echo":      lambda: [self._on_stop_echo(),
                                        self._feedback("Listening paused")],
            "clear_transcript": lambda: [self._on_clear(),
                                         self._feedback("Transcript cleared")],
            "screenshot":      lambda: self._screenshot(),
            "open_settings":   lambda: os.startfile("ms-settings:"),
            "file_explorer":   lambda: self._open_app("explorer"),
            "task_manager":    lambda: self._open_app("taskmgr"),
            "lock_screen":     lambda: subprocess.Popen("rundll32.exe user32.dll,LockWorkStation",
                                                         shell=True),
            "sleep":           lambda: subprocess.Popen("rundll32.exe powrprof.dll,SetSuspendState 0,1,0",
                                                         shell=True),
            "shutdown":        lambda: subprocess.Popen("shutdown /s /t 30", shell=True),
            "restart":         lambda: subprocess.Popen("shutdown /r /t 30", shell=True),
            "brightness_up":   lambda: self._brightness(+10),
            "brightness_down": lambda: self._brightness(-10),
            "force_type":      lambda: None,   # handled in main._on_result
        }

        try:
            fn = dispatch.get(a)
            if fn:
                fn()
            else:
                logger.warning("Unknown action: %s", a)
        except Exception as exc:
            logger.error("Execute error [%s]: %s", a, exc, exc_info=True)
            self._feedback(f"Command failed: {exc}")

    def record_typed(self, text: str) -> None:
        self._last_typed = text

    @property
    def mode(self) -> str:
        return self._mode

    # ------------------------------------------------------------------
    # Result builder
    # ------------------------------------------------------------------

    def _build_result(self, action: str, arg: str, raw: str,
                      match: re.Match) -> CommandResult | None:

        if action == "open_app":
            # Try to resolve — accept even if unknown (will attempt shell launch)
            return CommandResult(True, action, {"app_name": arg},
                                 raw, feedback=f"Opening {arg.title()}...")

        elif action == "close_app":
            return CommandResult(True, action, {"app_name": arg},
                                 raw, feedback=f"Closing {arg.title()}...")

        elif action == "play_music":
            return CommandResult(True, action, {"query": arg},
                                 raw, feedback=f"Playing: {arg}")

        elif action in ("pause_music", "resume_music", "next_track",
                        "prev_track", "toggle_mute"):
            return CommandResult(True, action, {}, raw)

        elif action in ("volume_up", "volume_down"):
            return CommandResult(True, action, {}, raw)

        elif action == "set_volume":
            return CommandResult(True, action, {"level": arg}, raw,
                                 feedback=f"Volume: {arg}%")

        elif action in ("search_web",):
            return CommandResult(True, action, {"query": arg},
                                 raw, feedback=f"Searching: {arg}")

        elif action == "open_url":
            url = arg if arg.startswith("http") else f"https://{arg}"
            return CommandResult(True, action, {"url": url},
                                 raw, feedback=f"Opening {arg}")

        elif action == "youtube":
            return CommandResult(True, action, {"query": arg},
                                 raw, feedback=f"YouTube: {arg}")

        elif action == "whatsapp":
            return CommandResult(True, action, {"contact": arg},
                                 raw, feedback=f"WhatsApp: {arg}")

        elif action == "switch_mode":
            mode = MODE_ALIASES.get(arg.lower())
            if not mode:
                return None
            return CommandResult(True, action, {"mode": mode},
                                 raw, feedback=f"Mode: {mode.title()}")

        elif action == "set_timer":
            grps = match.groups()
            amount = grps[0] if grps else "1"
            unit   = grps[1] if len(grps) > 1 else "min"
            return CommandResult(True, action,
                                 {"amount": amount, "unit": unit.lower()},
                                 raw, feedback=f"Timer: {amount} {unit}")

        elif action == "scroll":
            grps = match.groups()
            direction = grps[0] if grps else "down"
            amount    = grps[1] if len(grps) > 1 and grps[1] else "3"
            return CommandResult(True, action,
                                 {"direction": direction, "amount": amount},
                                 raw)

        elif action == "force_type":
            return CommandResult(False, action, {"text": arg}, arg)

        else:
            return CommandResult(True, action, {}, raw)

    # ------------------------------------------------------------------
    # Action implementations
    # ------------------------------------------------------------------

    def _open_app(self, name: str) -> None:
        """Open any app — static map first, then dynamic discovery."""
        from app_discovery import get_discovery, STATIC_MAP

        disc = self._discovery or get_discovery()
        exe = disc.find(name)

        if not exe:
            # Last resort: try the raw name as a shell command
            exe = name.lower().split()[0]

        self._feedback(f"Opening {name.title()}...")
        logger.info("Opening: %s → %s", name, exe)

        try:
            if exe.startswith("ms-") or exe.startswith("ms+"):
                os.startfile(exe)
            elif exe.startswith("http"):
                webbrowser.open(exe)
            elif exe.endswith(".lnk"):
                os.startfile(exe)
            else:
                subprocess.Popen(exe, shell=True,
                                  creationflags=subprocess.CREATE_NO_WINDOW)
        except Exception as exc:
            logger.warning("Open failed: %s", exc)
            self._feedback(f"Could not open {name}")

    def _close_app(self, name: str) -> None:
        """Close any running app by name — tries graceful then force."""
        from app_discovery import get_discovery

        disc = self._discovery or get_discovery()
        proc = disc.find_process(name)

        self._feedback(f"Closing {name.title()}...")
        logger.info("Closing process: %s", proc)

        try:
            import psutil
            closed = False
            name_lower = proc.lower().rstrip(".exe")
            for p in psutil.process_iter(["name", "pid"]):
                pname = p.info["name"].lower().rstrip(".exe")
                if pname == name_lower or name_lower in pname:
                    p.terminate()
                    closed = True
            if not closed:
                # Fallback to taskkill
                subprocess.Popen(f"taskkill /IM {proc} /F", shell=True,
                                  creationflags=subprocess.CREATE_NO_WINDOW)
        except ImportError:
            subprocess.Popen(f"taskkill /IM {proc} /F", shell=True,
                              creationflags=subprocess.CREATE_NO_WINDOW)

    def _play_music(self, query: str) -> None:
        """
        Smart music player:
          1. If Spotify is running → send via Spotify URI (offline app plays)
          2. Search local Music folder for matching file
          3. Fall back to YouTube search in browser
        """
        # Try Spotify URI first (works offline if Spotify cache has the song)
        if self._is_process_running("Spotify.exe"):
            spotify_uri = f"spotify:search:{quote_plus(query)}"
            try:
                os.startfile(spotify_uri)
                self._feedback(f"Spotify: {query}")
                logger.info("Spotify URI: %s", spotify_uri)
                return
            except Exception:
                pass

        # Try local Music folder
        local = self._find_local_music(query)
        if local:
            os.startfile(local)
            self._feedback(f"Playing: {Path(local).stem}")
            logger.info("Local music: %s", local)
            return

        # Fall back to YouTube
        url = f"https://www.youtube.com/results?search_query={quote_plus(query)}"
        webbrowser.open(url)
        self._feedback(f"YouTube: {query}")

    def _find_local_music(self, query: str) -> str:
        """Search user's Music folder for a file matching query."""
        import difflib
        music_dirs = [
            Path.home() / "Music",
            Path("C:/Users/Siddharth/Music"),
            Path("D:/Music"),
        ]
        exts = {".mp3", ".m4a", ".flac", ".ogg", ".wav", ".aac", ".wma"}
        all_files: list[Path] = []
        for d in music_dirs:
            if d.exists():
                all_files.extend(f for f in d.rglob("*") if f.suffix.lower() in exts)

        if not all_files:
            return ""

        # Match by stem name
        stems = [f.stem.lower() for f in all_files]
        matches = difflib.get_close_matches(query.lower(), stems, n=1, cutoff=0.4)
        if matches:
            idx = stems.index(matches[0])
            return str(all_files[idx])
        return ""

    def _media_key(self, key: str) -> None:
        """Send a Windows media key (playpause, nexttrack, prevtrack, volumemute)."""
        try:
            import keyboard
            keyboard.send(key)
            self._feedback({"playpause": "Play/Pause",
                            "nexttrack": "Next track",
                            "prevtrack": "Previous track",
                            "volumemute": "Mute toggled"}.get(key, key))
        except Exception as exc:
            logger.warning("Media key failed: %s", exc)

    def _volume_change(self, steps: int) -> None:
        """Change system volume by n steps (each step = ~2%)."""
        try:
            import keyboard
            key = "volumeup" if steps > 0 else "volumedown"
            for _ in range(abs(steps)):
                keyboard.send(key)
            self._feedback(f"Volume {'up' if steps > 0 else 'down'}")
        except Exception as exc:
            logger.warning("Volume change failed: %s", exc)

    def _set_volume(self, level: int) -> None:
        """Set system volume to exact percentage using PowerShell."""
        level = max(0, min(100, level))
        script = (
            f"$wsh = New-Object -ComObject WScript.Shell; "
            f"$vol = [int]({level}/2); "
            f"for ($i=0; $i -lt 50; $i++) {{ $wsh.SendKeys([char]174) }}; "
            f"for ($i=0; $i -lt $vol; $i++) {{ $wsh.SendKeys([char]175) }}"
        )
        subprocess.Popen(["powershell", "-Command", script],
                          creationflags=subprocess.CREATE_NO_WINDOW)
        self._feedback(f"Volume: {level}%")

    def _search_web(self, query: str) -> None:
        url = f"https://www.google.com/search?q={quote_plus(query)}"
        webbrowser.open(url)
        self._feedback(f"Searching: {query}")

    def _open_url(self, url: str) -> None:
        if not url.startswith("http"):
            url = "https://" + url
        webbrowser.open(url)
        self._feedback(f"Opening {url}")

    def _youtube(self, query: str) -> None:
        url = f"https://www.youtube.com/results?search_query={quote_plus(query)}"
        webbrowser.open(url)
        self._feedback(f"YouTube: {query}")

    def _whatsapp(self, contact: str) -> None:
        wa_exe = r"C:\Users\Siddharth\AppData\Local\WhatsApp\WhatsApp.exe"
        if os.path.exists(wa_exe):
            subprocess.Popen([wa_exe], creationflags=subprocess.CREATE_NO_WINDOW)
            self._feedback("WhatsApp opened")
        else:
            webbrowser.open("https://web.whatsapp.com/")
            self._feedback("WhatsApp Web opened")

    def _switch_mode(self, mode: str) -> None:
        self._mode = mode
        self._on_mode_change(mode)
        self._feedback(f"Mode: {mode.title()}")

    def _tell_time(self) -> None:
        now = datetime.datetime.now()
        t = now.strftime("%I:%M %p")
        self._feedback(f"Time: {t}")
        # Also type it into focused field if in note/message mode
        if self._mode in ("note", "message"):
            self._type_text(t)

    def _tell_date(self) -> None:
        now = datetime.datetime.now()
        d = now.strftime("%A, %d %B %Y")
        self._feedback(f"Date: {d}")
        if self._mode in ("note", "message"):
            self._type_text(d)

    def _set_timer(self, amount: int, unit: str) -> None:
        seconds = amount
        if "min" in unit:
            seconds = amount * 60
        elif "hour" in unit or "hr" in unit:
            seconds = amount * 3600
        label = f"{amount} {unit}"

        def _ring():
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                0,
                f"Timer done! ({label})",
                "NirmiqEcho Timer",
                0x40 | 0x1000  # MB_ICONINFORMATION | MB_SYSTEMMODAL
            )

        t = threading.Timer(seconds, _ring)
        t.daemon = True
        t.start()
        self._timers.append(t)
        self._feedback(f"Timer set: {label}")
        logger.info("Timer set: %d seconds", seconds)

    def _screenshot(self) -> None:
        try:
            import pyautogui
            pyautogui.hotkey("win", "printscreen")
            self._feedback("Screenshot saved")
        except Exception as exc:
            self._feedback(f"Screenshot failed: {exc}")

    def _hotkey(self, *keys: str) -> None:
        try:
            import pyautogui
            pyautogui.hotkey(*keys)
        except Exception as exc:
            logger.warning("Hotkey %s failed: %s", keys, exc)

    def _press(self, key: str) -> None:
        try:
            import pyautogui
            pyautogui.press(key)
        except Exception as exc:
            logger.warning("Press %s failed: %s", key, exc)

    def _scroll(self, direction: str = "down", amount: int = 3) -> None:
        try:
            import pyautogui
            clicks = amount if direction.lower() == "up" else -amount
            pyautogui.scroll(clicks * 100)
        except Exception as exc:
            logger.warning("Scroll failed: %s", exc)

    def _delete_last(self) -> None:
        if not self._last_typed:
            return
        try:
            import pyautogui
            pyautogui.press("backspace", presses=len(self._last_typed) + 1,
                             interval=0.005)
            self._feedback("Deleted")
        except Exception as exc:
            self._feedback(f"Delete failed: {exc}")

    def _type_text(self, text: str) -> None:
        try:
            import pyperclip, pyautogui
            pyperclip.copy(text)
            pyautogui.hotkey("ctrl", "v")
        except Exception as exc:
            logger.warning("Type text failed: %s", exc)

    def _brightness(self, delta: int) -> None:
        """Change screen brightness via PowerShell WMI."""
        script = (
            f"$mon = Get-WmiObject -Namespace root/wmi -Class WmiMonitorBrightness; "
            f"$current = $mon.CurrentBrightness; "
            f"$new = [Math]::Max(0,[Math]::Min(100,$current+({delta}))); "
            f"(Get-WmiObject -Namespace root/wmi -Class WmiMonitorBrightnessMethods)"
            f".WmiSetBrightness(1,$new)"
        )
        subprocess.Popen(["powershell", "-Command", script],
                          creationflags=subprocess.CREATE_NO_WINDOW)
        self._feedback(f"Brightness {'up' if delta > 0 else 'down'}")

    def _is_process_running(self, name: str) -> bool:
        try:
            import psutil
            return any(p.name().lower() == name.lower()
                       for p in psutil.process_iter(["name"]))
        except Exception:
            return False

    def _feedback(self, msg: str) -> None:
        logger.info("Feedback: %s", msg)
        self._on_feedback(msg)


# ─────────────────────────────────────────────────────────────────────
# Test
# ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(message)s")

    cp = CommandProcessor(on_feedback=lambda m: print(f"  >> {m}"))

    tests = [
        ("open Chrome",                  "CMD open_app"),
        ("open Brave",                   "CMD open_app"),
        ("close Spotify",                "CMD close_app"),
        ("play Shape of You",            "CMD play_music"),
        ("pause music",                  "CMD pause_music"),
        ("next track",                   "CMD next_track"),
        ("volume up",                    "CMD volume_up"),
        ("set volume to 50",             "CMD set_volume"),
        ("search for AI tutorials",      "CMD search_web"),
        ("YouTube coding music",         "CMD youtube"),
        ("go back",                      "CMD nav_back"),
        ("new tab",                      "CMD new_tab"),
        ("scroll down",                  "CMD scroll"),
        ("scroll down 5",                "CMD scroll"),
        ("switch window",                "CMD switch_window"),
        ("what time is it",              "CMD tell_time"),
        ("what is today",                "CMD tell_date"),
        ("set timer for 5 minutes",      "CMD set_timer"),
        ("note mode",                    "CMD switch_mode"),
        ("new line",                     "CMD new_line"),
        ("delete that",                  "CMD delete_last"),
        ("take a screenshot",            "CMD screenshot"),
        ("minimize",                     "CMD minimize_window"),
        ("close window",                 "CMD close_window"),
        ("stop echo",                    "CMD stop_echo"),
        ("clear transcript",             "CMD clear_transcript"),
        ("type open notepad please",     "TXT force_type"),
        ("Hello my name is Siddharth",   "TXT dictation"),
        ("I am building income systems", "TXT dictation"),
        ("WhatsApp Rahul",               "CMD whatsapp"),
        ("open github.com",              "CMD open_url"),
    ]

    print("CommandProcessor test:\n")
    ok = fail = 0
    for phrase, expected_kind in tests:
        result = cp.process(phrase)
        kind = f"CMD {result.action}" if result.is_command else "TXT dictation"
        # force_type → TXT
        if result.action == "force_type":
            kind = "TXT force_type"
        match = "OK" if kind == expected_kind else "FAIL"
        if match == "OK":
            ok += 1
        else:
            fail += 1
        print(f"  [{match}] '{phrase}'")
        if match == "FAIL":
            print(f"       Expected: {expected_kind}  Got: {kind}")
    print(f"\n{ok}/{ok+fail} passed")
