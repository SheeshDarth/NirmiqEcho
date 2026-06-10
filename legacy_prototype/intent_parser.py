"""
NirmiqEcho Intent Parser
Regex-first, Claude Haiku fallback (only for unmatched commands).
Pattern order matters — more specific patterns come first.
"""
from __future__ import annotations

import re
import json
import os
from functools import lru_cache

# ── helpers ───────────────────────────────────────────────────────────

def _g(m: re.Match, *indices) -> str:
    for i in indices:
        try:
            v = m.group(i)
            if v:
                return v.strip()
        except IndexError:
            pass
    return ""


# ── pattern table ─────────────────────────────────────────────────────
# (regex, intent, extractor(match) -> dict)

PATTERNS: list[tuple[str, str, callable]] = [

    # ── WhatsApp (before generic OPEN_APP) ──────────────────────────
    (
        r"(?:whatsapp|wa|message|text|msg|ping|send.*?to)\s+([a-z][a-z\s\-']+?)(?:\s+(?:and\s+)?(?:say|saying|that|with message)\s+(.+))?$",
        "WHATSAPP_MESSAGE",
        lambda m: {"contact": _g(m, 1), "message": _g(m, 2)},
    ),
    (
        r"(?:whatsapp\s+)?(?:video\s+call|vcall)\s+(.+)",
        "WHATSAPP_VIDEO_CALL",
        lambda m: {"contact": _g(m, 1)},
    ),
    (
        r"(?:call|ring|phone|dial)\s+(.+)\s+on\s+whatsapp",
        "WHATSAPP_CALL",
        lambda m: {"contact": _g(m, 1)},
    ),

    # ── Phone call ───────────────────────────────────────────────────
    (
        r"(?:call|ring|phone|dial)\s+(.+)",
        "CALL_CONTACT",
        lambda m: {"contact": _g(m, 1)},
    ),

    # ── App open / close ─────────────────────────────────────────────
    (
        r"(?:open|launch|start|run|switch to|go to)\s+(.+)",
        "OPEN_APP",
        lambda m: {"app": _g(m, 1)},
    ),
    (
        r"(?:close|quit|exit|kill|shut)\s+(.+)",
        "CLOSE_APP",
        lambda m: {"app": _g(m, 1)},
    ),
    (
        r"(?:minimize|minimise)\s+(.+)",
        "MINIMIZE_APP",
        lambda m: {"app": _g(m, 1)},
    ),

    # ── Typing ───────────────────────────────────────────────────────
    (
        r"(?:type|write|input|enter|insert)\s+(.+)",
        "TYPE_TEXT",
        lambda m: {"text": _g(m, 1)},
    ),
    (
        r"(?:press|hit|click)\s+(.+)",
        "PRESS_KEY",
        lambda m: {"key": _g(m, 1)},
    ),
    (
        r"(?:copy|cut|paste|undo|redo|save|select all)",
        "PRESS_KEY",
        lambda m: {"key": m.group(0).strip()},
    ),

    # ── Music ────────────────────────────────────────────────────────
    (
        r"(?:play|put on|start playing|queue)\s+(.+)",
        "PLAY_MUSIC",
        lambda m: {"query": _g(m, 1)},
    ),
    (r"(?:pause|pause music|pause (?:the\s+)?(?:song|music|audio))$", "PAUSE_MUSIC", lambda m: {}),
    (r"(?:stop music|stop (?:the\s+)?(?:song|music|audio)|stop playing)$", "STOP_MUSIC", lambda m: {}),
    (r"(?:next|next (?:song|track)|skip|skip (?:song|track))$", "NEXT_TRACK", lambda m: {}),
    (r"(?:previous|prev|(?:go\s+)?back|last (?:song|track))$", "PREV_TRACK", lambda m: {}),
    (r"(?:volume up|louder|increase volume|turn (?:it\s+)?up)", "VOLUME_UP", lambda m: {}),
    (r"(?:volume down|quieter|lower volume|decrease volume|turn (?:it\s+)?down)", "VOLUME_DOWN", lambda m: {}),
    (r"(?:mute|unmute|toggle mute)", "TOGGLE_MUTE", lambda m: {}),
    (r"set volume (?:to\s+)?(\d+)(?:\s+percent)?", "SET_VOLUME", lambda m: {"level": int(m.group(1))}),

    # ── Files ────────────────────────────────────────────────────────
    (
        r"(?:find|search (?:for)?|look for|locate|where is)\s+(.+?)(?:\s+in\s+(.+))?$",
        "SEARCH_FILE",
        lambda m: {"query": _g(m, 1), "location": _g(m, 2)},
    ),
    (
        r"(?:open|show|view)\s+(?:the\s+)?(?:file\s+)?(.+\.(?:pdf|docx?|xlsx?|pptx?|txt|py|js|ts|json|mp3|mp4|mkv|jpg|jpeg|png|gif|zip|rar|7z|exe|apk))\b",
        "OPEN_FILE",
        lambda m: {"filename": _g(m, 1)},
    ),
    (
        r"(?:show|open)\s+(?:my\s+)?(?:documents|downloads|desktop|music|videos|pictures|photos)",
        "OPEN_FOLDER",
        lambda m: {"folder": re.search(r"documents|downloads|desktop|music|videos|pictures|photos", m.group(0), re.I).group(0).lower()},
    ),

    # ── Browser ──────────────────────────────────────────────────────
    (
        r"(?:search|google|look up|bing)\s+(?:for\s+)?(.+)",
        "WEB_SEARCH",
        lambda m: {"query": _g(m, 1)},
    ),
    (
        r"(?:open|go to|visit|navigate to)\s+(?:the\s+)?(?:website\s+|site\s+|link\s+)?(.+\.(?:com|org|net|io|dev|ai|co|in|uk|us|gov)[\S]*)",
        "OPEN_URL",
        lambda m: {"url": _g(m, 1)},
    ),

    # ── System ───────────────────────────────────────────────────────
    (r"(?:shut down|shutdown|power off|turn off (?:the\s+)?(?:computer|laptop|pc))", "SHUTDOWN", lambda m: {}),
    (r"(?:restart|reboot|restart (?:the\s+)?(?:computer|laptop|pc))", "RESTART", lambda m: {}),
    (r"(?:sleep|hibernate|suspend)\b", "SLEEP", lambda m: {}),
    (r"(?:lock|lock (?:the\s+)?(?:screen|computer|pc))", "LOCK", lambda m: {}),
    (r"(?:take a\s+)?screenshot|capture (?:the\s+)?screen", "SCREENSHOT", lambda m: {}),
    (r"cancel shutdown|abort shutdown", "CANCEL_SHUTDOWN", lambda m: {}),

    # ── Clipboard ────────────────────────────────────────────────────
    (
        r"copy (?:that|this|the (?:text|content))",
        "PRESS_KEY",
        lambda m: {"key": "ctrl+c"},
    ),

    # ── Info ─────────────────────────────────────────────────────────
    (r"what(?:'s| is) (?:the\s+)?time|current time|what time is it", "GET_TIME", lambda m: {}),
    (r"what(?:'s| is) (?:the\s+)?date|current date|what day is it|what(?:'s| is) today", "GET_DATE", lambda m: {}),
    (r"what(?:'s| is) (?:the\s+)?(?:battery|battery level|battery status)", "GET_BATTERY", lambda m: {}),
    (r"what(?:'s| is) (?:the\s+)?(?:wifi|wi-fi|network|internet) (?:status|connection)", "GET_WIFI", lambda m: {}),
]


def parse_local(transcript: str) -> dict | None:
    text = transcript.lower().strip()
    # Strip common filler phrases
    text = re.sub(r"^(?:hey\s+)?(?:nirmiq|echo|jarvis)[,\s]+", "", text)
    text = re.sub(r"^(?:please|can you|could you|would you)\s+", "", text)

    for pattern, intent, extractor in PATTERNS:
        try:
            m = re.search(pattern, text, re.IGNORECASE)
            if m:
                return {"intent": intent, "params": extractor(m), "source": "regex"}
        except Exception:
            continue
    return None


@lru_cache(maxsize=1)
def _claude():
    key = os.getenv("ANTHROPIC_API_KEY", "")
    if not key:
        return None
    from anthropic import Anthropic
    return Anthropic(api_key=key)


_SYSTEM = """\
Parse voice commands into JSON. Return ONLY valid JSON: {"intent": "NAME", "params": {...}}

Available intents:
OPEN_APP {app}, CLOSE_APP {app}, MINIMIZE_APP {app},
WHATSAPP_MESSAGE {contact, message}, WHATSAPP_CALL {contact}, WHATSAPP_VIDEO_CALL {contact},
CALL_CONTACT {contact},
TYPE_TEXT {text}, PRESS_KEY {key},
PLAY_MUSIC {query}, PAUSE_MUSIC {}, STOP_MUSIC {}, NEXT_TRACK {}, PREV_TRACK {},
VOLUME_UP {}, VOLUME_DOWN {}, TOGGLE_MUTE {}, SET_VOLUME {level},
OPEN_FILE {filename}, SEARCH_FILE {query, location}, OPEN_FOLDER {folder},
WEB_SEARCH {query}, OPEN_URL {url},
SHUTDOWN {}, RESTART {}, SLEEP {}, LOCK {}, SCREENSHOT {}, CANCEL_SHUTDOWN {},
GET_TIME {}, GET_DATE {}, GET_BATTERY {}, GET_WIFI {},
UNKNOWN {raw}"""


async def parse_intent(transcript: str) -> dict:
    local = parse_local(transcript)
    if local:
        return local

    c = _claude()
    if not c:
        return {"intent": "UNKNOWN", "params": {"raw": transcript}, "source": "none"}

    try:
        resp = c.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=150,
            system=_SYSTEM,
            messages=[{"role": "user", "content": transcript}],
        )
        data = json.loads(resp.content[0].text.strip())
        data["source"] = "claude"
        return data
    except Exception:
        return {"intent": "UNKNOWN", "params": {"raw": transcript}, "source": "none"}


# Sync wrapper for non-async callers
def parse_intent_sync(transcript: str) -> dict:
    local = parse_local(transcript)
    if local:
        return local

    c = _claude()
    if not c:
        return {"intent": "UNKNOWN", "params": {"raw": transcript}, "source": "none"}

    try:
        resp = c.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=150,
            system=_SYSTEM,
            messages=[{"role": "user", "content": transcript}],
        )
        data = json.loads(resp.content[0].text.strip())
        data["source"] = "claude"
        return data
    except Exception:
        return {"intent": "UNKNOWN", "params": {"raw": transcript}, "source": "none"}
