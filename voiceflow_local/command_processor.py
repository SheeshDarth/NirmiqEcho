"""
command_processor.py - Full-scale Jarvis voice command engine for NirmiqEcho

Complete personal assistant — 100% offline, no LLM needed.

Command categories:
  App control      : open/close/switch/focus any installed app
  Music            : play local files → Spotify → YouTube; pause/next/prev/volume
  Navigation       : go back, forward, refresh, new tab, scroll
  Web              : search, Google, YouTube (auto-play first result)
  Messaging        : WhatsApp full flow (open → contact → type message → send)
                     Telegram, Discord
  System           : screenshot, volume, brightness, shutdown, restart, sleep
  Dictation        : new line, delete that, copy, paste, type [text]
  Time / Info      : what time is it, set timer, date, battery
  Echo control     : stop Echo, disable Echo
  Window control   : minimize, maximize, close, switch, show desktop
  File access      : open [file], find [file], open [folder], move/delete
  Multi-step       : stateful WhatsApp → contact → message flow

Flow:
  CommandProcessor.process(text) → CommandResult
  → is_command=True  : execute silently, speak feedback via TTS
  → is_command=False : check conversation state → if handled, skip typing
                       else: type text into focused app
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
from typing import Callable, Optional
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


# Conversational wrappers people say around a command — stripped before
# matching so "hey can you open chrome please" becomes "open chrome".
# (Applied only to command matching, never to a message being dictated.)
_CONV_LEAD = re.compile(
    r"^(?:(?:hi|hey|hello|yo|ok|okay|um|uh|so|well|alright|"
    r"echo|nirmiq|jarvis|please|kindly|just|now|"
    r"can you|could you|would you|will you|can u|"
    r"i want to|i wanna|i'd like to|i would like to|i need to|i need you to|"
    r"let's|lets|go ahead and|help me|for me)\b[\s,]*)+",
    re.IGNORECASE)
_CONV_TRAIL = re.compile(
    r"[\s,]*\b(?:please|for me|right now|real quick|thanks|thank you)\b[\s.!?]*$",
    re.IGNORECASE)


def _strip_conversational(text: str) -> str:
    """Remove leading/trailing politeness so natural phrasing still matches."""
    out = _CONV_LEAD.sub("", text).strip()
    out = _CONV_TRAIL.sub("", out).strip()
    return out or text   # never strip down to nothing


# Offline one-liners for the "tell me a joke" command (no external dependency).
_JOKES = [
    "Why do programmers prefer dark mode? Because light attracts bugs.",
    "I told my computer I needed a break, and now it won't stop sending me KitKat ads.",
    "Why did the developer go broke? Because he used up all his cache.",
    "There are 10 kinds of people in the world: those who understand binary and those who don't.",
    "Why was the JavaScript developer sad? Because he didn't know how to null his feelings.",
    "I would tell you a UDP joke, but you might not get it.",
    "Why do Java developers wear glasses? Because they don't C sharp.",
    "A SQL query walks into a bar, goes up to two tables and asks: can I join you?",
    "Why did the computer go to the doctor? It had a virus.",
    "I'm reading a book about anti-gravity. It's impossible to put down.",
]


# Voice-derived text must NEVER reach a shell unsanitized — a malicious
# audio clip ("open calc && ...") is a real injection vector for a
# voice-controlled assistant. Allow only benign name characters.
_SAFE_TOKEN_RE = re.compile(r"^[\w.+\- ()]+$")
_SAFE_PROC_RE  = re.compile(r"^[\w.+\- ()]+\.exe$", re.IGNORECASE)


# ─────────────────────────────────────────────────────────────────────
# Command patterns  (order = priority)
# ─────────────────────────────────────────────────────────────────────

PATTERNS: list[tuple[re.Pattern, str]] = [

    # ── Cancel ongoing conversation ──────────────────────────────────
    (_p(r"^(?:cancel|abort|never\s+mind|stop\s+that|forget\s+it)$"),
                                                             "cancel_intent"),

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
    (_p(r"^(?:what(?:'s|\s+is)?\s+)?(?:the\s+)?battery(?:\s+(?:level|percentage|status))?[\?]?$"),
                                                             "tell_battery"),
    (_p(r"^(?:what(?:'s|\s+is)?\s+)?(?:the\s+)?(?:cpu|c\.?p\.?u\.?)(?:\s+(?:usage|load))?[\?]?$"),
                                                             "tell_cpu"),
    (_p(r"^(?:system\s+status|how(?:'s|\s+is)\s+(?:my\s+|the\s+)?(?:system|pc|computer|laptop))[\?]?$"),
                                                             "system_status"),

    # ── Jokes ─────────────────────────────────────────────────────────
    (_p(r"^(?:tell\s+me\s+)?(?:a\s+)?joke(?:\s+please)?$"),  "tell_joke"),
    (_p(r"^(?:make\s+me\s+laugh|say\s+something\s+funny|got\s+any\s+jokes)$"),
                                                             "tell_joke"),

    # ── Remember / recall (lightweight local memory) ──────────────────
    (_p(r"^remember\s+(?:that\s+|this[:,]?\s+)?(.+)$"),      "remember"),
    (_p(r"^(?:what\s+do\s+you\s+remember|what\s+did\s+i\s+(?:tell|ask)\s+you\s+to\s+remember|recall(?:\s+everything)?|what\s+have\s+you\s+remembered)[\?]?$"),
                                                             "recall"),
    (_p(r"^(?:forget\s+everything|clear\s+(?:your\s+)?memory)$"),
                                                             "forget_all"),

    # ── Timer ────────────────────────────────────────────────────────
    (_p(r"^set\s+(?:a\s+)?timer\s+(?:for\s+)?(\d+)\s*(minute[s]?|min[s]?|second[s]?|sec[s]?|hour[s]?|hr[s]?)$"),
                                                             "set_timer"),
    (_p(r"^(?:remind\s+me\s+in)\s+(\d+)\s*(minute[s]?|min[s]?|second[s]?|hour[s]?|hr[s]?)$"),
                                                             "set_timer"),
    (_p(r"^(?:cancel|stop|clear)\s+(?:the\s+)?timer$"),     "cancel_timer"),

    # ── WhatsApp full flow ────────────────────────────────────────────
    (_p(r"^open\s+whatsapp$"),                              "open_whatsapp"),
    (_p(r"^(?:whatsapp|message|text|send(?:\s+a\s+message\s+to)?)\s+(.+?)\s+(?:and\s+)?(?:say|tell(?:\s+him|her|them)?)\s+(.+)$"),
                                                             "whatsapp_with_message"),
    (_p(r"^(?:message|text|whatsapp)\s+(.+?)$"),            "whatsapp_contact"),
    (_p(r"^send\s+(?:a\s+message\s+to\s+)?(.+?)$"),         "whatsapp_contact"),
    (_p(r"^(?:reply|respond)(?:\s+(?:to\s+)?(.+?))?(?:\s+(?:saying|with)\s+(.+))?$"),
                                                             "whatsapp_reply"),

    # ── Music control (extended) ─────────────────────────────────────
    (_p(r"^(?:play|put\s+on|listen\s+to)\s+(.+?)\s+on\s+spotify$"),
                                                             "play_spotify"),
    (_p(r"^(?:play|put\s+on|listen\s+to)\s+(.+?)\s+on\s+youtube$"),
                                                             "play_youtube_song"),
    (_p(r"^(?:play|put\s+on|listen\s+to)\s+(.+?)\s+locally$"),
                                                             "play_local"),
    (_p(r"^(?:play|put\s+on|listen\s+to)\s+(.+?)(?:\s+(?:song|music|track))?$"),
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
    (_p(r"^(?:shuffle|shuffle\s+(?:music|songs|all))$"),    "shuffle_music"),

    # ── Navigation ───────────────────────────────────────────────────
    (_p(r"^(?:go\s+)?back(?:\s+(?:button|page))?$"),        "nav_back"),
    (_p(r"^(?:go\s+)?forward(?:\s+(?:button|page))?$"),     "nav_forward"),
    (_p(r"^(?:refresh|reload)(?:\s+(?:page|tab))?$"),       "nav_refresh"),
    (_p(r"^(?:new\s+tab|open\s+(?:a\s+)?new\s+tab)$"),      "new_tab"),
    (_p(r"^(?:close\s+tab|close\s+this\s+tab)$"),           "close_tab"),
    (_p(r"^(?:next\s+tab|switch\s+tab)$"),                  "next_tab"),
    (_p(r"^scroll\s+(up|down)(?:\s+(\d+))?$"),              "scroll"),
    (_p(r"^(?:scroll\s+(?:up|down)|page\s+(?:up|down))$"),  "scroll"),
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
    (_p(r"^(?:snap|move)\s+(?:window\s+)?(?:to\s+)?(left|right)$"),
                                                             "snap_window"),

    # ── URL open ────────────────────────────────────────────────────
    (_p(r"^(?:open|go\s+to)\s+(https?://.+)$"),             "open_url"),
    (_p(r"^(?:go\s+to|open|visit)\s+(\S+\.(?:com|org|net|io|in|co|dev|app))(?:/\S*)?$"),
                                                             "open_url"),

    # ── File access ─────────────────────────────────────────────────
    (_p(r"^(?:open|show|view)\s+(?:my\s+)?(?:the\s+)?(.+?)\s+(?:file|document|spreadsheet|presentation|pdf)$"),
                                                             "open_file"),
    (_p(r"^(?:open|browse)\s+(?:my\s+)?(desktop|documents|downloads|pictures|photos|music|videos|movies|onedrive)$"),
                                                             "open_folder"),
    (_p(r"^(?:find|locate|where\s+is)\s+(?:the\s+file\s+)?(.+?)(?:\s+file)?$"),
                                                             "find_file"),
    (_p(r"^(?:what(?:'s|\s+is)\s+in|list)\s+(?:my\s+)?(desktop|documents|downloads|pictures|music|videos)$"),
                                                             "list_folder"),
    (_p(r"^(?:move|transfer)\s+(.+?)\s+to\s+(.+)$"),        "move_file"),
    (_p(r"^(?:delete|remove|trash)\s+(?:the\s+)?(.+?)\s+(?:file|folder|document)$"),
                                                             "delete_file"),

    # ── App launch ───────────────────────────────────────────────────
    (_p(r"^(?:open|launch|start|run)\s+(.+)$"),             "open_app"),

    # ── App close ────────────────────────────────────────────────────
    (_p(r"^(?:close|quit|exit|kill|shut\s+down)\s+(.+)$"),  "close_app"),

    # ── App focus / switch to ────────────────────────────────────────
    (_p(r"^(?:switch\s+to|focus|go\s+to|bring\s+up)\s+(.+)$"),
                                                             "focus_app"),

    # ── Web search ───────────────────────────────────────────────────
    (_p(r"^(?:search(?:\s+for)?|google(?:\s+for)?|look\s+up|how\s+(?:to|do))\s+(.+)$"),
                                                             "search_web"),
    # Spoken Q&A — answer aloud (Wikipedia → local LLM), web-search fallback.
    # Math / time / date / battery are matched earlier, so by here a "what is"
    # is a genuine factual question. The (?!you...) guard keeps self-questions
    # ("who are you") routing to the assistant's own introduction below.
    (_p(r"^(?:who\s+(?:is|are|was|were)\s+(?!you\b|u\b|yourself\b|i\b|me\b)"
        r"|what\s+(?:is|are|was|were)\s+|what's\s+"
        r"|tell\s+me\s+about\s+|how\s+(?:does|did)\s+)(.+)$"),
                                                             "answer_question"),

    # ── YouTube ──────────────────────────────────────────────────────
    (_p(r"^(?:youtube|watch|play\s+on\s+youtube)\s+(.+)$"), "youtube"),
    (_p(r"^(.+)\s+on\s+youtube$"),                          "youtube"),

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
    (_p(r"^(?:empty|clear)\s+(?:the\s+|my\s+)?(?:recycle\s+bin|trash|bin)$"),
                                                             "empty_recycle_bin"),
    (_p(r"^(?:open\s+)?clipboard$"),                        "show_clipboard"),

    # ── Personality / help ───────────────────────────────────────────
    (_p(r"^(?:help|what\s+can\s+you\s+do|list\s+(?:your\s+)?commands|show\s+commands)[\?]?$"),
                                                             "show_help"),
    (_p(r"^(?:who\s+are\s+you|what(?:'s|\s+is)\s+your\s+name|introduce\s+yourself)[\?]?$"),
                                                             "introduce"),
    (_p(r"^(?:thank\s+you|thanks(?:\s+echo)?|thank\s+you\s+echo)$"),
                                                             "acknowledge"),
    (_p(r"^good\s+(morning|afternoon|evening|night)(?:\s+echo)?$"),
                                                             "greet"),
    (_p(r"^(?:are\s+you\s+(?:there|awake|listening)|hello|hey\s+there)[\?]?$"),
                                                             "confirm_presence"),

    # ── Typing mode ──────────────────────────────────────────────────
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
# User-defined commands (commands.yaml)
# ─────────────────────────────────────────────────────────────────────
# Config phrases may bind ONLY to these already-validated, non-destructive
# actions. Destructive ones (shutdown/restart/sleep/delete/empty bin/close_app/
# whatsapp send) are intentionally excluded — config supplies phrasings, never
# new or dangerous behaviour. Each bound action still runs through the normal
# dispatch + its own arg validation + confirmation gates.
_CUSTOM_SAFE_ACTIONS = frozenset({
    "open_app", "focus_app", "open_folder", "open_url", "search_web", "youtube",
    "play_music", "play_spotify", "play_youtube_song", "play_local",
    "force_type", "find_file", "list_folder", "take_note", "tell_time",
    "tell_date", "tell_battery", "tell_cpu", "system_status", "answer_question",
    "calculate", "tell_joke", "volume_up", "volume_down", "toggle_mute",
    "set_volume", "scroll", "nav_back", "nav_forward", "new_tab", "screenshot",
    "minimize_window", "maximize_window", "show_desktop", "lock_screen",
    "open_whatsapp", "open_settings", "shuffle_music",
})


def load_custom_commands(path=None) -> list:
    """
    Load user-defined phrase→command bindings from commands.yaml.
    Returns a list of (compiled_pattern, action, args) for SAFE actions only.
    Never raises: missing file / missing PyYAML / bad entries are skipped.
    Phrases are re.escape'd so config can't inject regex.
    """
    if path is None:
        path = Path(__file__).resolve().parent.parent / "commands.yaml"
    path = Path(path)
    if not path.exists():
        return []
    try:
        import yaml
    except ImportError:
        logger.info("custom commands: PyYAML not installed — skipping "
                    "(pip install pyyaml to enable commands.yaml)")
        return []
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        logger.warning("custom commands: could not parse %s: %s", path, exc)
        return []

    out = []
    for entry in (data.get("commands") or []):
        if not isinstance(entry, dict):
            continue
        phrase = str(entry.get("phrase", "")).strip()
        action = str(entry.get("action", "")).strip()
        args = entry.get("args") or {}
        if not phrase or not action:
            continue
        if action not in _CUSTOM_SAFE_ACTIONS:
            logger.warning("custom commands: refusing unsafe/unknown action "
                           "%r for phrase %r", action, phrase)
            continue
        if not isinstance(args, dict):
            logger.warning("custom commands: args for %r must be a mapping", phrase)
            continue
        pat = re.compile(r"^\s*" + re.escape(phrase) + r"\s*$", re.IGNORECASE)
        out.append((pat, action, {str(k): v for k, v in args.items()}))
    if out:
        logger.info("custom commands: loaded %d from %s", len(out), path.name)
    return out


# ─────────────────────────────────────────────────────────────────────
# CommandProcessor
# ─────────────────────────────────────────────────────────────────────

class CommandProcessor:
    """
    Full-scale Jarvis-style voice command engine.
    Classifies and executes voice commands. Works 100% offline.

    Integrates:
      - TTSEngine         — spoken voice responses
      - ConversationState — multi-step intents (WhatsApp flow, etc.)
      - FileAssistant     — file system access
      - AppDiscovery      — dynamic Windows app discovery
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

        # User-defined phrase→command bindings (commands.yaml). Safe if absent.
        self._custom_commands = load_custom_commands()

        # Lazy-load subsystems to keep startup fast
        self._discovery = None
        self._tts = None
        self._conv = None
        self._file_assistant = None

        # Background: pre-warm app discovery cache
        threading.Thread(target=self._init_subsystems, daemon=True).start()

        logger.info("CommandProcessor: ready (%d patterns, %d custom)",
                    len(PATTERNS), len(self._custom_commands))

    def _init_subsystems(self):
        """Initialize all subsystems in background thread."""
        # App discovery
        from app_discovery import get_discovery
        self._discovery = get_discovery()
        self._discovery._build_cache()

        # TTS Engine
        from tts_engine import get_tts
        self._tts = get_tts()

        # Conversation state
        from conversation_state import ConversationStateManager
        self._conv = ConversationStateManager(on_prompt=self._tts_speak)

        # File assistant
        from file_assistant import get_file_assistant
        self._file_assistant = get_file_assistant()

        logger.info("CommandProcessor: all subsystems ready")

    # ------------------------------------------------------------------
    # TTS helpers
    # ------------------------------------------------------------------

    def _tts_speak(self, text: str) -> None:
        """Speak via TTS if available, always show in UI feedback."""
        if self._tts and self._tts.is_available:
            self._tts.speak(text)
        self._feedback(text)

    def _tts_interrupt(self, text: str) -> None:
        if self._tts and self._tts.is_available:
            self._tts.speak_interrupt(text)
        self._feedback(text)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def process(self, text: str, _allow_fallback: bool = True) -> CommandResult:
        """
        Classify text as command or dictation.

        FIRST checks if conversation state machine can handle it
        (e.g. we're mid-WhatsApp flow). If nothing matches and the optional
        local-LLM fallback is available, the phrasing is rewritten into a
        canonical command and re-matched (so novel wording still works).
        """
        # Strip ALL trailing punctuation Whisper may add ("Open Chrome!", "...?")
        cleaned = text.strip().rstrip(".!?,;:")

        # 1. Check active conversation state (multi-step intent).
        #    Uses the RAW cleaned text — a message being dictated into WhatsApp
        #    ("hey, how are you") must not have its words stripped.
        if self._conv and not self._conv.is_idle:
            consumed = self._conv.handle_input(cleaned)
            if consumed:
                # Consumed by state machine — return as command (silent)
                return CommandResult(
                    is_command=True,
                    action="conversation_step",
                    raw_text=text,
                    feedback="",
                )

        # Strip conversational wrappers for command matching only, so
        # "hey can you open chrome please" -> "open chrome".
        cleaned = _strip_conversational(cleaned)

        # 2. Math — only fires when the phrase actually has numbers + an
        #    operator, so "what is the capital of France" still hits search.
        try:
            from calculator import calculate
            calc = calculate(cleaned)
        except Exception:
            calc = None
        if calc:
            result_str, spoken = calc
            return CommandResult(True, "calculate",
                                 {"result": result_str, "spoken": spoken},
                                 text, feedback=f"= {result_str}")

        # 3. Unit conversion + date math — also offline & deterministic
        try:
            from units import convert as _convert, date_query as _date_query
            conv = _convert(cleaned) or _date_query(cleaned)
        except Exception:
            conv = None
        if conv:
            result_str, spoken = conv
            return CommandResult(True, "calculate",
                                 {"result": result_str, "spoken": spoken},
                                 text, feedback=result_str)

        # 2. Pattern match against PATTERNS list
        for pattern, action in PATTERNS:
            m = pattern.match(cleaned)
            if m:
                arg = m.group(1).strip() if m.lastindex else ""
                result = self._build_result(action, arg, text, m)
                if result is not None:
                    logger.info("Command: %s | %r", action, arg)
                    return result

        # 3. User-defined commands (commands.yaml) — built-ins win, then these
        #    fill the gap. Each binds an exact phrase to an already-validated
        #    SAFE action with fixed args; it executes through the same dispatch.
        for pattern, action, cargs in self._custom_commands:
            if pattern.match(cleaned):
                logger.info("Custom command: %r -> %s", cleaned, action)
                return CommandResult(True, action, dict(cargs), text,
                                     feedback=f"{action.replace('_', ' ')}")

        # 5. Local-LLM fallback — map a novel phrasing to a known command and
        #    re-run the engine on it. Only in default (command) mode, only when
        #    Ollama is reachable; otherwise this is an instant no-op.
        if _allow_fallback and self._mode == "default":
            try:
                import llm_fallback
                mapped = llm_fallback.map_to_command(cleaned)
            except Exception as exc:
                logger.debug("llm_fallback error: %s", exc)
                mapped = None
            if mapped and mapped.strip().lower() != cleaned.lower():
                logger.info("LLM fallback: %r -> %r", cleaned, mapped)
                result = self.process(mapped, _allow_fallback=False)
                if result.is_command:
                    return result

        return CommandResult(is_command=False, raw_text=text)

    def execute(self, result: CommandResult) -> None:
        """Execute a recognised command."""
        a = result.action
        g = result.args

        # conversation_step is already handled in process() — no-op here
        if a == "conversation_step":
            return

        # Audit trail — every executed command is logged locally (accountability;
        # never leaves the machine, gitignored).
        self._audit(a, g)

        dispatch = {
            "open_app":           lambda: self._open_app(g.get("app_name", "")),
            "close_app":          lambda: self._close_app(g.get("app_name", "")),
            "focus_app":          lambda: self._focus_app(g.get("app_name", "")),
            "play_music":         lambda: self._play_music(g.get("query", "")),
            "play_spotify":       lambda: self._play_spotify(g.get("query", "")),
            "play_youtube_song":  lambda: self._play_youtube_song(g.get("query", "")),
            "play_local":         lambda: self._play_local(g.get("query", "")),
            "pause_music":        lambda: self._media_key("playpause"),
            "resume_music":       lambda: self._media_key("playpause"),
            "next_track":         lambda: self._media_key("nexttrack"),
            "prev_track":         lambda: self._media_key("prevtrack"),
            "volume_up":          lambda: self._volume_change(+2),
            "volume_down":        lambda: self._volume_change(-2),
            "toggle_mute":        lambda: self._media_key("volumemute"),
            "set_volume":         lambda: self._set_volume(int(g.get("level", 50))),
            "shuffle_music":      lambda: self._shuffle_music(),
            "search_web":         lambda: self._search_web(g.get("query", "")),
            "open_url":           lambda: self._open_url(g.get("url", "")),
            "youtube":            lambda: self._youtube(g.get("query", "")),
            "open_whatsapp":      lambda: self._open_whatsapp(),
            "whatsapp_contact":   lambda: self._whatsapp_start_flow(g.get("contact", "")),
            "whatsapp_with_message": lambda: self._whatsapp_send(
                                        g.get("contact", ""), g.get("message", "")),
            "whatsapp_reply":     lambda: self._whatsapp_reply(g.get("message", "")),
            "switch_mode":        lambda: self._switch_mode(g.get("mode", "default")),
            "tell_time":          lambda: self._tell_time(),
            "tell_date":          lambda: self._tell_date(),
            "tell_battery":       lambda: self._tell_battery(),
            "tell_cpu":           lambda: self._tell_cpu(),
            "system_status":      lambda: self._system_status(),
            "answer_question":    lambda: self._answer_question(g.get("query", "")),
            "tell_joke":          lambda: self._tell_joke(),
            "remember":           lambda: self._remember(g.get("text", "")),
            "recall":             lambda: self._recall(),
            "forget_all":         lambda: self._forget_all(),
            "set_timer":          lambda: self._set_timer(int(g.get("amount", 1)),
                                                           g.get("unit", "min")),
            "cancel_timer":       lambda: self._cancel_timers(),
            "cancel_intent":      lambda: self._cancel_intent(),
            "nav_back":           lambda: self._hotkey("alt", "left"),
            "nav_forward":        lambda: self._hotkey("alt", "right"),
            "nav_refresh":        lambda: self._hotkey("f5"),
            "new_tab":            lambda: self._hotkey("ctrl", "t"),
            "close_tab":          lambda: self._hotkey("ctrl", "w"),
            "next_tab":           lambda: self._hotkey("ctrl", "tab"),
            "scroll":             lambda: self._scroll(g.get("direction", "down"),
                                                       int(g.get("amount", 3))),
            "scroll_top":         lambda: self._hotkey("ctrl", "home"),
            "scroll_bottom":      lambda: self._hotkey("ctrl", "end"),
            "switch_window":      lambda: self._hotkey("alt", "tab"),
            "zoom_in":            lambda: self._hotkey("ctrl", "+"),
            "zoom_out":           lambda: self._hotkey("ctrl", "-"),
            "snap_window":        lambda: self._snap_window(g.get("direction", "left")),
            "new_line":           lambda: self._press("enter"),
            "new_paragraph":      lambda: [self._press("enter"), self._press("enter")],
            "press_tab":          lambda: self._press("tab"),
            "delete_last":        lambda: self._delete_last(),
            "copy_clipboard":     lambda: self._hotkey("ctrl", "c"),
            "paste_clipboard":    lambda: self._hotkey("ctrl", "v"),
            "undo":               lambda: self._hotkey("ctrl", "z"),
            "redo":               lambda: self._hotkey("ctrl", "y"),
            "select_all":         lambda: self._hotkey("ctrl", "a"),
            "minimize_window":    lambda: self._hotkey("win", "down"),
            "maximize_window":    lambda: self._hotkey("win", "up"),
            "close_window":       lambda: self._hotkey("alt", "f4"),
            "restore_window":     lambda: self._hotkey("win", "up"),
            "show_desktop":       lambda: self._hotkey("win", "d"),
            "stop_echo":          lambda: [self._on_stop_echo(),
                                           self._tts_speak("Echo off.")],
            "pause_echo":         lambda: [self._on_stop_echo(),
                                           self._tts_speak("Listening paused.")],
            "clear_transcript":   lambda: [self._on_clear(),
                                           self._feedback("Transcript cleared")],
            "screenshot":         lambda: self._screenshot(),
            "open_settings":      lambda: os.startfile("ms-settings:"),
            "file_explorer":      lambda: self._open_app("explorer"),
            "task_manager":       lambda: self._open_app("taskmgr"),
            # Lock is instant — non-destructive and instantly recoverable.
            "lock_screen":        lambda: subprocess.Popen(
                                      ["rundll32.exe", "user32.dll,LockWorkStation"],
                                      shell=False),
            # Destructive / disruptive → require spoken confirmation so a
            # misheard command can never sleep/restart/wipe the machine.
            "sleep":              lambda: self._require_confirm(
                                      self._do_sleep,
                                      "Put the computer to sleep? Say yes to confirm."),
            "shutdown":           lambda: self._require_confirm(
                                      self._do_shutdown,
                                      "Shut down the computer in 30 seconds? Say yes to confirm.",
                                      cancel_msg="Shutdown cancelled."),
            "restart":            lambda: self._require_confirm(
                                      self._do_restart,
                                      "Restart the computer in 30 seconds? Say yes to confirm.",
                                      cancel_msg="Restart cancelled."),
            "brightness_up":      lambda: self._brightness(+10),
            "brightness_down":    lambda: self._brightness(-10),
            "empty_recycle_bin":  lambda: self._require_confirm(
                                      self._empty_recycle_bin,
                                      "Permanently empty the recycle bin? Say yes to confirm."),
            "show_clipboard":     lambda: self._hotkey("win", "v"),
            "open_file":          lambda: self._voice_open_file(g.get("filename", "")),
            "open_folder":        lambda: self._voice_open_folder(g.get("folder", "")),
            "find_file":          lambda: self._voice_find_file(g.get("query", "")),
            "list_folder":        lambda: self._voice_list_folder(g.get("folder", "")),
            "move_file":          lambda: self._voice_move_file(
                                        g.get("src", ""), g.get("dst", "")),
            "delete_file":        lambda: self._voice_delete_file(g.get("filename", "")),
            "calculate":          lambda: self._calculate(g.get("result", ""),
                                                           g.get("spoken", "")),
            "show_help":          lambda: self._show_help(),
            "introduce":          lambda: self._introduce(),
            "acknowledge":        lambda: self._tts_speak("Anytime."),
            "greet":              lambda: self._greet(g.get("when", "")),
            "confirm_presence":   lambda: self._tts_speak("I'm here. Listening."),
            "force_type":         lambda: None,   # handled in main._on_result
        }

        try:
            fn = dispatch.get(a)
            if fn:
                fn()
            else:
                logger.warning("Unknown action: %s", a)
        except Exception as exc:
            logger.error("Execute error [%s]: %s", a, exc, exc_info=True)
            self._tts_speak(f"Command failed.")

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
            return CommandResult(True, action, {"app_name": arg},
                                 raw, feedback=f"Opening {arg.title()}...")

        elif action == "close_app":
            return CommandResult(True, action, {"app_name": arg},
                                 raw, feedback=f"Closing {arg.title()}...")

        elif action == "focus_app":
            return CommandResult(True, action, {"app_name": arg},
                                 raw, feedback=f"Switching to {arg.title()}...")

        elif action in ("play_music", "play_spotify", "play_youtube_song", "play_local"):
            return CommandResult(True, action, {"query": arg},
                                 raw, feedback=f"Playing: {arg}")

        elif action in ("pause_music", "resume_music", "next_track",
                        "prev_track", "toggle_mute", "shuffle_music"):
            return CommandResult(True, action, {}, raw)

        elif action in ("volume_up", "volume_down"):
            return CommandResult(True, action, {}, raw)

        elif action == "set_volume":
            return CommandResult(True, action, {"level": arg}, raw,
                                 feedback=f"Volume: {arg}%")

        elif action in ("search_web",):
            return CommandResult(True, action, {"query": arg},
                                 raw, feedback=f"Searching: {arg}")

        elif action == "answer_question":
            return CommandResult(True, action, {"query": arg},
                                 raw, feedback=f"Looking that up...")

        elif action == "remember":
            return CommandResult(True, action, {"text": arg},
                                 raw, feedback="Noted.")

        elif action == "open_url":
            url = arg if arg.startswith("http") else f"https://{arg}"
            return CommandResult(True, action, {"url": url},
                                 raw, feedback=f"Opening {arg}")

        elif action == "youtube":
            return CommandResult(True, action, {"query": arg},
                                 raw, feedback=f"YouTube: {arg}")

        elif action == "open_whatsapp":
            return CommandResult(True, action, {}, raw, feedback="Opening WhatsApp...")

        elif action == "whatsapp_contact":
            return CommandResult(True, action, {"contact": arg},
                                 raw, feedback=f"Messaging {arg}...")

        elif action == "whatsapp_with_message":
            grps = match.groups()
            contact = grps[0].strip() if grps else ""
            message = grps[1].strip() if len(grps) > 1 else ""
            return CommandResult(True, action, {"contact": contact, "message": message},
                                 raw, feedback=f"Sending to {contact}...")

        elif action == "whatsapp_reply":
            grps = match.groups()
            message = (grps[1] or "").strip() if grps and len(grps) > 1 else ""
            return CommandResult(True, action, {"message": message},
                                 raw, feedback="Replying...")

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

        elif action == "snap_window":
            direction = arg or "left"
            return CommandResult(True, action, {"direction": direction}, raw)

        elif action == "open_file":
            return CommandResult(True, action, {"filename": arg},
                                 raw, feedback=f"Finding {arg}...")

        elif action == "open_folder":
            return CommandResult(True, action, {"folder": arg},
                                 raw, feedback=f"Opening {arg.title()}...")

        elif action == "find_file":
            return CommandResult(True, action, {"query": arg},
                                 raw, feedback=f"Searching for {arg}...")

        elif action == "list_folder":
            return CommandResult(True, action, {"folder": arg}, raw)

        elif action == "move_file":
            grps = match.groups()
            src = grps[0].strip() if grps else ""
            dst = grps[1].strip() if len(grps) > 1 else ""
            return CommandResult(True, action, {"src": src, "dst": dst},
                                 raw, feedback=f"Moving {src} to {dst}...")

        elif action == "delete_file":
            return CommandResult(True, action, {"filename": arg},
                                 raw, feedback=f"Deleting {arg}...")

        elif action == "greet":
            return CommandResult(True, action, {"when": arg}, raw)

        elif action == "force_type":
            return CommandResult(False, action, {"text": arg}, arg)

        else:
            return CommandResult(True, action, {}, raw)

    # ------------------------------------------------------------------
    # App control
    # ------------------------------------------------------------------

    def _open_app(self, name: str) -> None:
        """Open any app — focus if already running, else launch."""
        from app_discovery import get_discovery

        disc = self._discovery or get_discovery()

        # Try focus first (bring existing window to front)
        if self._focus_running_app(name):
            return

        exe = disc.find(name)
        if not exe:
            exe = name.lower().split()[0]

        self._tts_speak(f"Opening {name.title()}")
        logger.info("Opening: %s → %s", name, exe)

        try:
            self._launch_executable(exe)
        except Exception as exc:
            logger.warning("Open failed: %s", exc)
            self._tts_speak(f"Could not open {name}")

    @staticmethod
    def _launch_executable(exe: str) -> None:
        """
        Launch an app WITHOUT ever passing voice-derived text to a shell.
        Handles: ms- protocols, URLs, .lnk shortcuts, absolute paths,
        bare names ("chrome", "calc") and name+args ("jupyter notebook").
        """
        exe = exe.strip()
        if exe.startswith("http"):
            webbrowser.open(exe)
            return
        # Protocol handlers: ms-settings:, spotify:, outlookcal:, … —
        # a URI scheme, not a drive letter ("C:\...")
        if re.match(r"^[A-Za-z][\w+.-]+:", exe) and not re.match(r"^[A-Za-z]:[\\/]", exe):
            os.startfile(exe)
            return
        if exe.lower().endswith(".lnk") or os.path.isfile(exe):
            os.startfile(exe)
            return

        # Bare command name — validate before doing anything with it
        if not _SAFE_TOKEN_RE.match(exe):
            raise ValueError(f"unsafe executable string rejected: {exe!r}")

        import shutil as _shutil
        parts = exe.split()
        resolved = _shutil.which(parts[0])
        if resolved:
            subprocess.Popen([resolved, *parts[1:]], shell=False,
                             creationflags=subprocess.CREATE_NO_WINDOW)
            return
        # Last resort: ShellExecute resolves App Paths entries (chrome.exe …)
        target = parts[0] if parts[0].lower().endswith((".exe", ".msc")) \
            else parts[0] + ".exe"
        os.startfile(target)

    def _close_app(self, name: str) -> None:
        from app_discovery import get_discovery
        disc = self._discovery or get_discovery()
        proc = disc.find_process(name)

        # Voice-derived process name — refuse anything that isn't a plain
        # "name.exe" before it can reach taskkill
        if not _SAFE_PROC_RE.match(proc):
            logger.warning("Rejected unsafe process name: %r", proc)
            self._tts_speak(f"I couldn't identify the app {name}.")
            return

        self._tts_speak(f"Closing {name.title()}")
        logger.info("Closing process: %s", proc)

        try:
            import psutil
            closed = False
            name_lower = proc.lower().removesuffix(".exe")
            for p in psutil.process_iter(["name", "pid"]):
                pname = p.info["name"].lower().removesuffix(".exe")
                if pname == name_lower or name_lower in pname:
                    p.terminate()
                    closed = True
            if not closed:
                subprocess.Popen(["taskkill", "/IM", proc, "/F"], shell=False,
                                  creationflags=subprocess.CREATE_NO_WINDOW)
        except ImportError:
            subprocess.Popen(["taskkill", "/IM", proc, "/F"], shell=False,
                              creationflags=subprocess.CREATE_NO_WINDOW)

    def _focus_app(self, name: str) -> None:
        """Bring an app window to the foreground."""
        if not self._focus_running_app(name):
            # Not running — launch it
            self._open_app(name)
        else:
            self._tts_speak(f"Switched to {name.title()}")

    def _focus_running_app(self, name: str) -> bool:
        """
        Try to focus an already-running app window.
        Returns True if we successfully focused it.
        """
        from app_discovery import get_discovery, PROCESS_ALIASES
        import difflib

        disc = self._discovery or get_discovery()
        proc_name = disc.find_process(name)
        if not proc_name:
            return False

        # PowerShell: bring window to foreground.
        # proc_base is interpolated into a PS command — strip everything
        # except benign name characters (voice-derived = untrusted).
        proc_base = re.sub(r"[^\w.+\- ()]", "", Path(proc_name).stem)
        if not proc_base:
            return False
        script = (
            f"$proc = Get-Process '{proc_base}' -ErrorAction SilentlyContinue | "
            f"Select-Object -First 1; "
            f"if ($proc) {{ "
            f"  $hwnd = $proc.MainWindowHandle; "
            f"  Add-Type -TypeDefinition '"
            f"    using System; using System.Runtime.InteropServices; "
            f"    public class Win32 {{ "
            f"      [DllImport(\"user32.dll\")] public static extern bool SetForegroundWindow(IntPtr h); "
            f"      [DllImport(\"user32.dll\")] public static extern bool ShowWindow(IntPtr h, int n); "
            f"    }}"
            f"  '; "
            f"  [Win32]::ShowWindow($hwnd, 9); "
            f"  [Win32]::SetForegroundWindow($hwnd) "
            f"}}"
        )
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", script],
                capture_output=True, timeout=3,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            # Check if process was found
            if result.returncode == 0:
                self._tts_speak(f"Switched to {name.title()}")
                logger.info("Focused: %s", name)
                return True
        except Exception as exc:
            logger.debug("focus_running_app failed: %s", exc)
        return False

    # ------------------------------------------------------------------
    # Music
    # ------------------------------------------------------------------

    def _play_music(self, query: str) -> None:
        """
        Smart music player priority:
          1. Local file (~/Music and common dirs) — plays with default player
          2. Spotify (if running) — sends URI
          3. YouTube — opens auto-play URL in browser
        """
        # 1. Local file
        local = self._find_local_music(query)
        if local:
            os.startfile(local)
            name = Path(local).stem
            self._tts_speak(f"Playing {name}")
            logger.info("Local music: %s", local)
            return

        # 2. Spotify (if running)
        if self._is_process_running("Spotify.exe"):
            self._play_spotify(query)
            return

        # 3. YouTube auto-play (ytsearch embed trick)
        self._play_youtube_song(query)

    def _play_local(self, query: str) -> None:
        """Play local file only — no fallback."""
        local = self._find_local_music(query)
        if local:
            os.startfile(local)
            self._tts_speak(f"Playing {Path(local).stem}")
        else:
            self._tts_speak(f"I couldn't find '{query}' in your music library.")

    # Spotify window titles that mean "nothing is playing"
    _SPOTIFY_IDLE_TITLES = {
        "spotify premium", "spotify free", "spotify", "advertisement", ""}

    def _spotify_window_title(self) -> str:
        try:
            import pygetwindow as gw
            for w in gw.getAllWindows():
                if "spotify" in (w.title or "").lower() and w.visible:
                    return w.title.strip()
        except Exception:
            pass
        return ""

    def _spotify_is_playing(self) -> bool:
        """Spotify's window title becomes 'Artist - Song' during playback."""
        return self._spotify_window_title().lower() not in self._SPOTIFY_IDLE_TITLES

    def _play_spotify(self, query: str) -> None:
        """
        Spotify play via the desktop app, no API/cloud keys:
          1. launch/focus Spotify (Store-app-safe `spotify:` URI)
          2. load search results for the query (reliable)
          3. best-effort: play the top result, then VERIFY via the window
             title and report honestly (no fake "Playing" claims).

        Spotify has no documented "play top result" shortcut, so step 3 is
        inherently best-effort. SPOTIFY_PLAY_TABS tunes the keyboard reach;
        if playback can't be confirmed Echo says so and leaves the results
        on screen for a one-click start. Truly reliable Spotify playback
        needs the Web API (track URI) — a later opt-in.
        """
        try:
            import pyautogui

            if not self._is_process_running("Spotify.exe"):
                os.startfile("spotify:")        # Store-app-safe cold start
                time.sleep(4.0)

            self._focus_window("spotify", timeout=8.0)
            time.sleep(0.4)
            os.startfile(f"spotify:search:{quote_plus(query)}")
            time.sleep(2.5)                      # let results render

            if os.getenv("SPOTIFY_AUTOPLAY", "1") != "0":
                self._focus_window("spotify", timeout=4.0)
                tabs = int(os.getenv("SPOTIFY_PLAY_TABS", "4"))
                for _ in range(max(0, tabs)):
                    pyautogui.press("tab")
                    time.sleep(0.15)
                pyautogui.press("enter")
                time.sleep(1.8)

            # Verify — don't lie about playback
            if self._spotify_is_playing():
                self._tts_speak(f"Playing {self._spotify_window_title()} on Spotify.")
            else:
                self._tts_speak(
                    f"I've pulled up {query} on Spotify. Press play to start it.")
            logger.info("Spotify: searched %r (playing=%s)",
                        query, self._spotify_is_playing())
        except Exception as exc:
            logger.warning("Spotify play failed: %s", exc)
            self._tts_speak("I couldn't control Spotify. Trying YouTube.")
            self._play_youtube_song(query)

    def _play_youtube_song(self, query: str) -> None:
        """
        Open YouTube and auto-click the first result by appending
        the ytsearch URL with &autoplay=1. The user just needs to
        click on the first result, or we use the direct watch URL trick.
        """
        # Use YouTube's search-then-redirect pattern
        # Opening ?search_query= puts the video at top and browser auto-plays
        url = f"https://www.youtube.com/results?search_query={quote_plus(query)}"
        webbrowser.open(url)
        self._tts_speak(f"Opening YouTube for {query}")
        logger.info("YouTube song: %s", url)

    def _shuffle_music(self) -> None:
        """Pick a random local music file and play it."""
        import random
        music_dirs = self._get_music_dirs()
        exts = {".mp3", ".m4a", ".flac", ".ogg", ".wav", ".aac", ".wma"}
        all_files: list[Path] = []
        for d in music_dirs:
            if d.exists():
                all_files.extend(f for f in d.rglob("*") if f.suffix.lower() in exts)
        if not all_files:
            self._tts_speak("No local music files found.")
            return
        chosen = random.choice(all_files)
        os.startfile(str(chosen))
        self._tts_speak(f"Shuffling — playing {chosen.stem}")

    def _find_local_music(self, query: str) -> str:
        """Search user's Music folder and common locations for a matching file."""
        import difflib
        music_dirs = self._get_music_dirs()
        exts = {".mp3", ".m4a", ".flac", ".ogg", ".wav", ".aac", ".wma"}
        all_files: list[Path] = []
        for d in music_dirs:
            if d.exists():
                all_files.extend(f for f in d.rglob("*") if f.suffix.lower() in exts)

        if not all_files:
            return ""

        stems = [f.stem.lower() for f in all_files]
        q = query.lower()

        # Exact
        if q in stems:
            return str(all_files[stems.index(q)])

        # Fuzzy
        matches = difflib.get_close_matches(q, stems, n=1, cutoff=0.40)
        if matches:
            return str(all_files[stems.index(matches[0])])

        # Substring
        for i, stem in enumerate(stems):
            if q in stem or stem in q:
                return str(all_files[i])

        return ""

    def _get_music_dirs(self) -> list[Path]:
        home = Path.home()
        return [
            home / "Music",
            Path("C:/Users/Siddharth/Music"),
            Path("D:/Music"),
            Path("E:/Music"),
            home / "Downloads",   # many people keep music in Downloads
        ]

    def _media_key(self, key: str) -> None:
        try:
            import keyboard
            keyboard.send(key)
            self._feedback({
                "playpause": "Play/Pause",
                "nexttrack": "Next track",
                "prevtrack": "Previous track",
                "volumemute": "Mute toggled",
            }.get(key, key))
        except Exception as exc:
            logger.warning("Media key failed: %s", exc)

    def _volume_change(self, steps: int) -> None:
        try:
            import keyboard
            key = "volumeup" if steps > 0 else "volumedown"
            for _ in range(abs(steps)):
                keyboard.send(key)
            self._feedback(f"Volume {'up' if steps > 0 else 'down'}")
        except Exception as exc:
            logger.warning("Volume change failed: %s", exc)

    def _set_volume(self, level: int) -> None:
        level = max(0, min(100, level))
        script = (
            f"$wsh = New-Object -ComObject WScript.Shell; "
            f"$vol = [int]({level}/2); "
            f"for ($i=0; $i -lt 50; $i++) {{ $wsh.SendKeys([char]174) }}; "
            f"for ($i=0; $i -lt $vol; $i++) {{ $wsh.SendKeys([char]175) }}"
        )
        subprocess.Popen(["powershell", "-Command", script],
                          creationflags=subprocess.CREATE_NO_WINDOW)
        self._tts_speak(f"Volume set to {level} percent")

    # ------------------------------------------------------------------
    # WhatsApp Full Automation
    # ------------------------------------------------------------------

    def _open_whatsapp(self) -> None:
        """Open WhatsApp desktop app."""
        self._open_app("whatsapp")
        self._tts_speak("WhatsApp is opening.")

    def _whatsapp_start_flow(self, contact: str) -> None:
        """
        Start the WhatsApp multi-step flow.
        If contact provided: open WA, search contact, wait for message.
        If no contact: ask for it.
        """
        if not self._conv:
            # Subsystems not ready yet — try simpler approach
            self._open_whatsapp()
            return

        from conversation_state import State

        if contact:
            # We have the contact — open WA, navigate to contact, wait for message
            self._tts_speak(f"Opening WhatsApp to message {contact}. What should I say?")
            threading.Thread(
                target=self._whatsapp_navigate_to_contact,
                args=(contact,),
                daemon=True,
            ).start()
            self._conv.begin_intent(
                intent="whatsapp",
                state=State.AWAITING_MESSAGE,
                on_complete=self._whatsapp_type_message,
                data={"contact": contact},
                prompt="",  # already spoken
            )
        else:
            self._conv.begin_intent(
                intent="whatsapp",
                state=State.AWAITING_CONTACT,
                on_complete=self._whatsapp_full_flow,
                prompt="Who do you want to message?",
            )

    def _whatsapp_full_flow(self, contact: str = "", message: str = "") -> None:
        """Called by ConversationState when both contact and message are known."""
        opened = self._whatsapp_navigate_to_contact(contact)
        if opened:
            time.sleep(0.8)
            self._whatsapp_type_message(contact=contact, message=message)

    def _whatsapp_send(self, contact: str, message: str) -> None:
        """Single-shot: 'WhatsApp Rahul and say hello there'."""
        threading.Thread(
            target=self._whatsapp_full_flow,
            kwargs={"contact": contact, "message": message},
            daemon=True,
        ).start()
        self._tts_speak(f"Sending message to {contact}")

    def _whatsapp_reply(self, message: str = "") -> None:
        """Reply in the currently open WhatsApp chat."""
        if not message:
            if self._conv:
                from conversation_state import State
                self._conv.begin_intent(
                    intent="whatsapp",
                    state=State.AWAITING_MESSAGE,
                    on_complete=lambda message="": self._whatsapp_type_message(
                        contact="", message=message),
                    prompt="What should I type?",
                )
            return
        self._whatsapp_type_message(contact="", message=message)

    def _whatsapp_paste(self, text: str) -> None:
        """Clipboard paste — Unicode-safe and fast (typewrite drops chars)."""
        import pyautogui, pyperclip
        pyperclip.copy(text)
        time.sleep(0.05)
        pyautogui.hotkey("ctrl", "v")

    @staticmethod
    def _launch_whatsapp() -> bool:
        """
        Launch WhatsApp Desktop across install types:
          1. whatsapp: URI  (Store app + standalone both register this)
          2. shell:AppsFolder  (Microsoft Store package)
          3. legacy standalone .exe
          4. WhatsApp Web in the browser (last resort)
        Returns True if a launch was issued.
        """
        # 1. Protocol handler
        try:
            os.startfile("whatsapp:")
            return True
        except Exception:
            pass
        # 2. Microsoft Store package
        try:
            out = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "(Get-AppxPackage -Name '*WhatsApp*').PackageFamilyName"],
                capture_output=True, text=True, timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW)
            fam = (out.stdout or "").strip().splitlines()
            if fam and fam[0]:
                os.startfile(f"shell:AppsFolder\\{fam[0]}!App")
                return True
        except Exception:
            pass
        # 3. Legacy standalone install
        legacy = os.path.expandvars(r"%LOCALAPPDATA%\WhatsApp\WhatsApp.exe")
        if os.path.exists(legacy):
            subprocess.Popen([legacy], creationflags=subprocess.CREATE_NO_WINDOW)
            return True
        # 4. Web fallback
        try:
            webbrowser.open("https://web.whatsapp.com/")
            return True
        except Exception:
            return False

    @staticmethod
    def _force_foreground(hwnd: int) -> None:
        """
        Force a window to the foreground, defeating Windows' foreground-lock
        (which blocks background processes like Echo from stealing focus).
        The Alt-key tap resets the lock so SetForegroundWindow is honoured.
        """
        import ctypes
        user32 = ctypes.windll.user32
        SW_RESTORE = 9
        VK_MENU = 0x12          # Alt
        KEYEVENTF_KEYUP = 0x0002
        try:
            user32.ShowWindow(hwnd, SW_RESTORE)
            # tap Alt to release the foreground lock, then claim foreground
            user32.keybd_event(VK_MENU, 0, 0, 0)
            user32.SetForegroundWindow(hwnd)
            user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
            user32.BringWindowToTop(hwnd)
        except Exception as exc:
            logger.debug("force_foreground failed: %s", exc)

    def _focus_window(self, title_substring: str, timeout: float = 8.0) -> bool:
        """
        Bring a window whose title contains `title_substring` to the
        foreground and confirm it is genuinely active. Defeats the Windows
        foreground-lock so it works even though Echo is a background process.
        Returns True only when that window actually owns the foreground — so
        we never type into the wrong app.
        """
        needle = title_substring.lower()
        try:
            import pygetwindow as gw
            import ctypes
        except Exception:
            return False
        user32 = ctypes.windll.user32
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            wins = [w for w in gw.getAllWindows()
                    if needle in (w.title or "").lower() and w.visible]
            for w in wins:
                hwnd = getattr(w, "_hWnd", None)
                if not hwnd:
                    continue
                self._force_foreground(hwnd)
                time.sleep(0.4)
                if user32.GetForegroundWindow() == hwnd:
                    return True
            time.sleep(0.3)
        return False

    def _focus_whatsapp_window(self, timeout: float = 8.0) -> bool:
        return self._focus_window("whatsapp", timeout)

    def _whatsapp_navigate_to_contact(self, contact: str) -> bool:
        """
        Open/focus WhatsApp and open the chat with `contact`. Returns True on
        success. Uses Ctrl+N (New chat — the real WhatsApp Desktop shortcut),
        clipboard paste, and window-focus verification so we never type into
        the wrong app.
        """
        try:
            import pyautogui

            launched = False
            if not self._is_process_running("WhatsApp.exe"):
                if not self._launch_whatsapp():
                    self._tts_speak("WhatsApp desktop isn't installed.")
                    return False
                launched = True

            # Wait for the WhatsApp window and make SURE it is focused
            if not self._focus_whatsapp_window(timeout=12.0 if launched else 6.0):
                self._tts_speak("I couldn't focus WhatsApp. Is it open?")
                logger.warning("WhatsApp window never became active")
                return False
            time.sleep(0.6 if not launched else 1.2)

            # Clear any open chat / dialog, then open New-chat search
            pyautogui.press("escape")
            time.sleep(0.2)
            pyautogui.hotkey("ctrl", "n")     # New chat → focuses search field
            time.sleep(0.8)

            # Type the contact name (paste = Unicode-safe, no dropped chars)
            self._whatsapp_paste(contact)
            time.sleep(1.2)                   # let the contact list filter

            # Select the first match and open it
            pyautogui.press("down")
            time.sleep(0.3)
            pyautogui.press("enter")
            time.sleep(0.8)

            logger.info("WhatsApp: opened chat with %s", contact)
            return True

        except Exception as exc:
            logger.error("WhatsApp navigate error: %s", exc, exc_info=True)
            self._tts_speak("WhatsApp navigation failed.")
            return False

    def _whatsapp_type_message(self, contact: str = "", message: str = "") -> None:
        """Type the message in the active WhatsApp chat and send it."""
        if not message:
            return
        try:
            import pyautogui

            # Make sure WhatsApp is still the focused window before we type —
            # guards against the user clicking away mid-flow.
            if not self._focus_whatsapp_window(timeout=4.0):
                self._tts_speak("WhatsApp lost focus, message not sent.")
                return

            time.sleep(0.3)
            self._whatsapp_paste(message)
            time.sleep(0.3)
            pyautogui.press("enter")
            self._tts_speak(f"Message sent to {contact}" if contact else "Message sent.")
            logger.info("WhatsApp: sent to %s: %r", contact, message[:40])

        except Exception as exc:
            logger.error("WhatsApp type message error: %s", exc)
            self._tts_speak("Failed to send the message.")

    # ------------------------------------------------------------------
    # Web
    # ------------------------------------------------------------------

    def _search_web(self, query: str) -> None:
        url = f"https://www.google.com/search?q={quote_plus(query)}"
        webbrowser.open(url)
        self._tts_speak(f"Searching for {query}")

    def _open_url(self, url: str) -> None:
        if not url.startswith("http"):
            url = "https://" + url
        webbrowser.open(url)
        self._feedback(f"Opening {url}")

    def _youtube(self, query: str) -> None:
        url = f"https://www.youtube.com/results?search_query={quote_plus(query)}"
        webbrowser.open(url)
        self._tts_speak(f"YouTube: {query}")

    # ------------------------------------------------------------------
    # File access (delegates to FileAssistant)
    # ------------------------------------------------------------------

    def _voice_open_file(self, filename: str) -> None:
        if not self._file_assistant:
            from file_assistant import get_file_assistant
            self._file_assistant = get_file_assistant()
        ok, msg = self._file_assistant.open_file(filename)
        self._tts_speak(msg)

    def _voice_open_folder(self, folder: str) -> None:
        if not self._file_assistant:
            from file_assistant import get_file_assistant
            self._file_assistant = get_file_assistant()
        ok, msg = self._file_assistant.open_folder(folder)
        self._tts_speak(msg)

    def _voice_find_file(self, query: str) -> None:
        if not self._file_assistant:
            from file_assistant import get_file_assistant
            self._file_assistant = get_file_assistant()
        matches = self._file_assistant.find_files(query, n=3)
        if not matches:
            self._tts_speak(f"I couldn't find any file matching '{query}'.")
        elif len(matches) == 1:
            self._tts_speak(f"Found: {matches[0].name} in {matches[0].parent.name}.")
        else:
            names = ", ".join(m.name for m in matches[:3])
            self._tts_speak(f"I found {len(matches)} matches: {names}")

    def _voice_list_folder(self, folder: str) -> None:
        if not self._file_assistant:
            from file_assistant import get_file_assistant
            self._file_assistant = get_file_assistant()
        ok, msg = self._file_assistant.list_folder(folder)
        self._tts_speak(msg)

    def _voice_move_file(self, src: str, dst: str) -> None:
        if not self._file_assistant:
            from file_assistant import get_file_assistant
            self._file_assistant = get_file_assistant()
        ok, msg = self._file_assistant.move_file(src, dst)
        self._tts_speak(msg)

    def _voice_delete_file(self, filename: str) -> None:
        """Ask for confirmation before deleting."""
        if not self._file_assistant:
            from file_assistant import get_file_assistant
            self._file_assistant = get_file_assistant()

        match = self._file_assistant.find_file(filename)
        if not match:
            self._tts_speak(f"I couldn't find '{filename}'.")
            return

        if not self._conv:
            # No state machine — just delete with a warning
            ok, msg, _ = self._file_assistant.delete_file(filename)
            self._tts_speak(msg)
            return

        from conversation_state import State

        def _do_delete(path=None):
            try:
                import send2trash
                send2trash.send2trash(str(match))
                self._tts_speak(f"Moved {match.name} to the Recycle Bin.")
            except Exception:
                try:
                    os.remove(str(match))
                    self._tts_speak(f"Deleted {match.name}.")
                except Exception as exc:
                    self._tts_speak(f"Couldn't delete: {exc}")

        self._conv.begin_intent(
            intent="file_delete",
            state=State.AWAITING_CONFIRM,
            on_complete=_do_delete,
            data={"path": str(match)},
            prompt=f"Are you sure you want to delete {match.name}? Say yes to confirm.",
        )

    # ------------------------------------------------------------------
    # System
    # ------------------------------------------------------------------

    def _switch_mode(self, mode: str) -> None:
        self._mode = mode
        self._on_mode_change(mode)
        self._tts_speak(f"Switched to {mode} mode.")

    def _tell_time(self) -> None:
        now = datetime.datetime.now()
        t = now.strftime("%I:%M %p")
        self._tts_speak(f"It's {t}")
        if self._mode in ("note", "message"):
            self._type_text(t)

    def _tell_date(self) -> None:
        now = datetime.datetime.now()
        d = now.strftime("%A, %d %B %Y")
        self._tts_speak(f"Today is {d}")
        if self._mode in ("note", "message"):
            self._type_text(d)

    def _tell_battery(self) -> None:
        try:
            import psutil
            batt = psutil.sensors_battery()
            if batt:
                pct = int(batt.percent)
                charging = "charging" if batt.power_plugged else "not charging"
                self._tts_speak(f"Battery is at {pct} percent, {charging}.")
            else:
                self._tts_speak("Battery info not available.")
        except Exception:
            self._tts_speak("Battery info not available.")

    def _tell_cpu(self) -> None:
        try:
            import psutil
            cpu = psutil.cpu_percent(interval=0.4)
            self._tts_speak(f"CPU usage is at {int(cpu)} percent.")
        except Exception:
            self._tts_speak("I couldn't read the CPU usage.")

    def _system_status(self) -> None:
        try:
            import psutil
            cpu = psutil.cpu_percent(interval=0.4)
            mem = psutil.virtual_memory().percent
            parts = [f"CPU at {int(cpu)} percent", f"memory at {int(mem)} percent"]
            batt = psutil.sensors_battery()
            if batt:
                parts.append(f"battery at {int(batt.percent)} percent")
            self._tts_speak("System status: " + ", ".join(parts) + ".")
        except Exception:
            self._tts_speak("I couldn't read the system status.")

    def _answer_question(self, query: str) -> None:
        """Speak a concise answer (Wikipedia → local LLM); else web-search."""
        query = (query or "").strip()
        if not query:
            return
        ans = None
        try:
            import knowledge
            ans = knowledge.answer(query)
        except Exception as exc:
            logger.debug("answer_question error: %s", exc)
        if ans:
            self._tts_speak(ans)
        else:
            # No offline/online answer available — fall back to a web search.
            self._tts_speak(f"Here's what I found for {query}.")
            self._search_web(query)

    def _tell_joke(self) -> None:
        import random
        self._tts_speak(random.choice(_JOKES))

    # ── lightweight remember / recall (local JSON) ────────────────────
    def _memory_path(self):
        return Path(__file__).resolve().parent / "assets" / "memory.json"

    def _load_facts(self) -> list:
        import json
        p = self._memory_path()
        try:
            return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []
        except Exception:
            return []

    def _save_facts(self, facts: list) -> None:
        import json
        p = self._memory_path()
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(facts, ensure_ascii=False, indent=2),
                         encoding="utf-8")
        except Exception as exc:
            logger.warning("could not save memory: %s", exc)

    def _remember(self, text: str) -> None:
        text = (text or "").strip()
        if not text:
            self._tts_speak("What should I remember?")
            return
        facts = self._load_facts()
        facts.append(text)
        self._save_facts(facts)
        self._tts_speak("Okay, I'll remember that.")

    def _recall(self) -> None:
        facts = self._load_facts()
        if not facts:
            self._tts_speak("You haven't asked me to remember anything yet.")
            return
        recent = facts[-5:]
        self._tts_speak("Here's what I remember. " + ". ".join(recent) + ".")

    def _forget_all(self) -> None:
        self._save_facts([])
        self._tts_speak("Done. I've cleared everything you asked me to remember.")

    def _set_timer(self, amount: int, unit: str) -> None:
        seconds = amount
        if "min" in unit:
            seconds = amount * 60
        elif "hour" in unit or "hr" in unit:
            seconds = amount * 3600
        label = f"{amount} {unit}"

        self._tts_speak(f"Timer set for {label}.")

        def _ring():
            self._tts_interrupt(f"Timer done! {label} have elapsed.")
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                0,
                f"Timer done! ({label})",
                "NirmiqEcho Timer",
                0x40 | 0x1000
            )

        t = threading.Timer(seconds, _ring)
        t.daemon = True
        t.start()
        self._timers.append(t)
        logger.info("Timer set: %d seconds", seconds)

    def _cancel_timers(self) -> None:
        active = [t for t in self._timers if t.is_alive()]
        for t in active:
            t.cancel()
        self._timers = []
        self._tts_speak(f"Cancelled {len(active)} timer{'s' if len(active) != 1 else ''}.")

    def _cancel_intent(self) -> None:
        if self._conv:
            self._conv.reset()
        self._tts_speak("Okay, cancelled.")

    def _calculate(self, result: str, spoken: str) -> None:
        """Speak the computed answer; type it too if in a typing mode."""
        self._tts_speak(spoken or f"The answer is {result}.")
        if self._mode in ("note", "message") and result:
            self._type_text(result)

    def _show_help(self) -> None:
        self._tts_speak(
            "I can open and close apps, message people on WhatsApp, "
            "play music locally or on Spotify and YouTube, search the web, "
            "find and open your files, control windows, volume, and brightness, "
            "set timers, take screenshots, and type whatever you dictate. "
            "Just speak naturally."
        )

    def _introduce(self) -> None:
        self._tts_speak(
            "I'm Echo. Every Command, Handled Offline. "
            "Your personal assistant, built by Siddharth. "
            "I run entirely on this machine — nothing leaves your laptop."
        )

    def _greet(self, when: str) -> None:
        hour = datetime.datetime.now().hour
        if hour < 12:
            actual = "morning"
        elif hour < 17:
            actual = "afternoon"
        else:
            actual = "evening"
        self._tts_speak(f"Good {actual}, Siddharth. Ready when you are.")

    def _screenshot(self) -> None:
        try:
            import pyautogui
            pyautogui.hotkey("win", "printscreen")
            self._tts_speak("Screenshot saved.")
        except Exception as exc:
            self._tts_speak(f"Screenshot failed.")

    # ── Local audit trail ────────────────────────────────────────────
    def _audit(self, action: str, args: dict) -> None:
        """Append a timestamped record of every executed command. Local only,
        gitignored — gives an accountability trail without phoning home."""
        try:
            import datetime
            line = (f"{datetime.datetime.now().isoformat(timespec='seconds')}  "
                    f"{action}  {args}\n")
            log = Path(__file__).resolve().parent / "assets" / "command_log.txt"
            log.parent.mkdir(parents=True, exist_ok=True)
            # Trim if it grows past ~500 KB so it never balloons.
            if log.exists() and log.stat().st_size > 512_000:
                tail = log.read_text(encoding="utf-8", errors="ignore").splitlines()[-2000:]
                log.write_text("\n".join(tail) + "\n", encoding="utf-8")
            with open(log, "a", encoding="utf-8") as fh:
                fh.write(line)
        except Exception:
            pass  # auditing must never break command execution

    # ── Confirmation gate for destructive / disruptive actions ───────
    def _require_confirm(self, action, prompt: str,
                         cancel_msg: str = "Okay, cancelled.") -> None:
        """
        Speak `prompt` and wait for a spoken yes/no before running `action`.
        Prevents a single misheard command from sleeping/restarting/wiping the
        machine. Falls back to running directly only if no conversation state
        is available (it always is in normal operation).
        """
        if self._conv:
            from conversation_state import State
            self._conv.begin_intent(
                intent="confirm_action",
                state=State.AWAITING_CONFIRM,
                on_complete=action,
                data={"_cancel_msg": cancel_msg},
                prompt=prompt,
            )
        else:
            action()

    def _do_shutdown(self) -> None:
        self._tts_speak("Shutting down in 30 seconds.")
        subprocess.Popen(["shutdown", "/s", "/t", "30"], shell=False,
                         creationflags=subprocess.CREATE_NO_WINDOW)

    def _do_restart(self) -> None:
        self._tts_speak("Restarting in 30 seconds.")
        subprocess.Popen(["shutdown", "/r", "/t", "30"], shell=False,
                         creationflags=subprocess.CREATE_NO_WINDOW)

    def _do_sleep(self) -> None:
        self._tts_speak("Going to sleep.")
        subprocess.Popen(
            ["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"],
            shell=False, creationflags=subprocess.CREATE_NO_WINDOW)

    def _empty_recycle_bin(self) -> None:
        try:
            script = "Clear-RecycleBin -Force -ErrorAction SilentlyContinue"
            subprocess.Popen(["powershell", "-Command", script],
                              creationflags=subprocess.CREATE_NO_WINDOW)
            self._tts_speak("Recycle bin emptied.")
        except Exception:
            self._tts_speak("Couldn't empty recycle bin.")

    def _brightness(self, delta: int) -> None:
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

    # ------------------------------------------------------------------
    # Keyboard / mouse
    # ------------------------------------------------------------------

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

    def _snap_window(self, direction: str = "left") -> None:
        try:
            import pyautogui
            if direction.lower() == "left":
                pyautogui.hotkey("win", "left")
            else:
                pyautogui.hotkey("win", "right")
        except Exception as exc:
            logger.warning("Snap failed: %s", exc)

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

    # ------------------------------------------------------------------
    # Process utilities
    # ------------------------------------------------------------------

    def _is_process_running(self, name: str) -> bool:
        try:
            import psutil
            return any(p.name().lower() == name.lower()
                       for p in psutil.process_iter(["name"]))
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Feedback
    # ------------------------------------------------------------------

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
        ("open Chrome",                          "CMD open_app"),
        ("open Brave",                           "CMD open_app"),
        ("close Spotify",                        "CMD close_app"),
        ("switch to Chrome",                     "CMD focus_app"),
        ("play Shape of You",                    "CMD play_music"),
        ("play Shape of You on spotify",         "CMD play_spotify"),
        ("play Shape of You on youtube",         "CMD play_youtube_song"),
        ("play Shape of You locally",            "CMD play_local"),
        ("shuffle music",                        "CMD shuffle_music"),
        ("pause music",                          "CMD pause_music"),
        ("next track",                           "CMD next_track"),
        ("volume up",                            "CMD volume_up"),
        ("set volume to 50",                     "CMD set_volume"),
        ("search for AI tutorials",              "CMD search_web"),
        ("YouTube coding music",                 "CMD youtube"),
        ("go back",                              "CMD nav_back"),
        ("new tab",                              "CMD new_tab"),
        ("scroll down",                          "CMD scroll"),
        ("scroll down 5",                        "CMD scroll"),
        ("switch window",                        "CMD switch_window"),
        ("what time is it",                      "CMD tell_time"),
        ("what is today",                        "CMD tell_date"),
        ("battery",                              "CMD tell_battery"),
        ("set timer for 5 minutes",              "CMD set_timer"),
        ("cancel timer",                         "CMD cancel_timer"),
        ("note mode",                            "CMD switch_mode"),
        ("new line",                             "CMD new_line"),
        ("delete that",                          "CMD delete_last"),
        ("take a screenshot",                    "CMD screenshot"),
        ("minimize",                             "CMD minimize_window"),
        ("close window",                         "CMD close_window"),
        ("snap window to left",                  "CMD snap_window"),
        ("stop echo",                            "CMD stop_echo"),
        ("clear transcript",                     "CMD clear_transcript"),
        ("cancel",                               "CMD cancel_intent"),
        ("open WhatsApp",                        "CMD open_whatsapp"),
        ("message Rahul",                        "CMD whatsapp_contact"),
        ("WhatsApp Rahul and say hey bro",       "CMD whatsapp_with_message"),
        ("open my resume file",                  "CMD open_file"),
        ("open downloads",                       "CMD open_folder"),
        ("find budget spreadsheet",              "CMD find_file"),
        ("what's in documents",                  "CMD list_folder"),
        ("delete report file",                   "CMD delete_file"),
        ("type open notepad please",             "TXT force_type"),
        ("Hello my name is Siddharth",           "TXT dictation"),
    ]

    print("CommandProcessor test:\n")
    ok = fail = 0
    for phrase, expected_kind in tests:
        result = cp.process(phrase)
        kind = f"CMD {result.action}" if result.is_command else "TXT dictation"
        if result.action == "force_type":
            kind = "TXT force_type"
        match_str = "OK" if kind == expected_kind else "FAIL"
        if match_str == "OK":
            ok += 1
        else:
            fail += 1
        print(f"  [{match_str}] '{phrase}'")
        if match_str == "FAIL":
            print(f"       Expected: {expected_kind}  Got: {kind}")
    print(f"\n{ok}/{ok+fail} passed")
