"""
llm_fallback.py — optional local-LLM understanding for NirmiqEcho.

When the fast offline regex engine doesn't recognise a spoken request, this
asks a LOCAL Ollama model to rewrite it as ONE canonical command the assistant
already knows. That gives Echo "understand anything" phrasing without giving up
its offline-first nature:

  • Pure localhost (http://localhost:11434) — no cloud, no API key.
  • Zero extra dependencies — uses urllib from the standard library.
  • If Ollama isn't running it returns None *instantly* (cached health check),
    so the assistant behaves exactly as it always has when offline.

Config (env / .env):
  LLM_FALLBACK=0      disable entirely
  OLLAMA_MODEL=...     model to use (default qwen3.5:4b)
  OLLAMA_URL=...       endpoint  (default http://localhost:11434)
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
import urllib.request

logger = logging.getLogger(__name__)

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434").rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3.5:4b")
FALLBACK_ENABLED = os.getenv("LLM_FALLBACK", "1") != "0"


def _is_local(url: str) -> bool:
    """True if the Ollama endpoint is on this machine (no data leaves it)."""
    try:
        from urllib.parse import urlparse
        host = (urlparse(url).hostname or "").lower()
        return host in ("localhost", "127.0.0.1", "::1", "0.0.0.0", "")
    except Exception:
        return False


# Privacy guard: NirmiqEcho is offline-first. If someone points OLLAMA_URL at a
# remote host, voice transcripts would leave the machine — warn loudly once.
if FALLBACK_ENABLED and not _is_local(OLLAMA_URL):
    logger.warning(
        "PRIVACY: OLLAMA_URL=%s is NOT local — voice transcripts will be sent "
        "off this machine. Set OLLAMA_URL to http://localhost:11434 to stay "
        "fully offline, or LLM_FALLBACK=0 to disable.", OLLAMA_URL)

_REQUEST_TIMEOUT = 30.0     # tolerate a cold model load on the first call
_HEALTH_TIMEOUT = 1.5
_HEALTH_TTL = 30.0          # re-probe Ollama at most this often
_KEEP_ALIVE = "30m"         # keep the model resident so later calls are fast
_MAX_WORDS = 12             # skip long utterances (likely dictation, not a command)

# Canonical commands the regex engine understands — keep roughly in sync with
# command_processor.PATTERNS. The model must output one of these shapes.
_CANONICAL = """open [app]
close [app]
switch to [app]
play [song]
play [song] on spotify
play [song] on youtube
pause music
next track
previous track
volume up
volume down
mute
set volume to [0-100]
message [contact] saying [message]
search for [query]
[query] on youtube
go to [website]
find [filename]
open downloads
open documents
take a note [text]
what are my recent notes
set a timer for [N] minutes
what time is it
what's the date
battery
scroll up
scroll down
go back
new tab
switch window
minimize
maximize
show desktop
snap left
snap right
take a screenshot
lock screen
empty recycle bin
brightness up
brightness down
calculate [expression]
convert [value and units]
who is [topic]
what is [topic]
tell me a joke
remember [text]
what do you remember
cpu usage
system status
type [text]"""

_SYSTEM = (
    "You map a user's spoken request to EXACTLY ONE command for the NirmiqEcho "
    "voice assistant, chosen from the canonical command list below, with the "
    "[slots] filled in from the request.\n"
    "Reply with ONLY that single command line — no quotes, no markdown, no "
    "explanation. If the request is ordinary dictation or conversation rather "
    "than an actionable command, reply with exactly: NONE\n\n"
    "Canonical commands:\n" + _CANONICAL
)

_available: bool | None = None
_available_checked = 0.0


def is_available() -> bool:
    """Cheap cached check that Ollama is reachable. False => skip the fallback."""
    global _available, _available_checked
    if not FALLBACK_ENABLED:
        return False
    now = time.monotonic()
    if _available is not None and (now - _available_checked) < _HEALTH_TTL:
        return _available
    _available_checked = now
    try:
        with urllib.request.urlopen(OLLAMA_URL + "/api/tags",
                                    timeout=_HEALTH_TIMEOUT):
            _available = True
    except Exception:
        _available = False
        logger.debug("llm_fallback: Ollama not reachable — fallback disabled")
    return _available


def map_to_command(text: str, context: str = "") -> str | None:
    """
    Rewrite a novel phrasing as a canonical command, or return None when the
    fallback is unavailable / the request isn't a command / it's too long.

    `context` is the previous request (if any). It lets follow-ups resolve
    pronouns — e.g. after "what is the Eiffel Tower", "how tall is it" becomes
    "what is the height of the Eiffel Tower".
    """
    text = (text or "").strip()
    if not text or len(text.split()) > _MAX_WORDS:
        return None
    if not is_available():
        return None

    user_msg = text
    if context:
        user_msg = (f"Previous request: {context}\nNow: {text}\n"
                    f"Resolve any pronouns (it, that, there, this) using the "
                    f"previous request, then output the single command.")

    body = json.dumps({
        "model": OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": user_msg},
        ],
        "stream": False,
        "think": False,             # skip chain-of-thought (qwen3.5 etc.) — fast
        "keep_alive": _KEEP_ALIVE,
        "options": {"temperature": 0.0, "num_predict": 48},
    }).encode("utf-8")

    try:
        req = urllib.request.Request(
            OLLAMA_URL + "/api/chat", data=body,
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        out = (data.get("message", {}) or {}).get("content", "") or ""
    except Exception as exc:
        # A timeout just means the model is busy/cold — not that Ollama is gone,
        # so we do NOT flip availability off here (only the health probe does).
        logger.debug("llm_fallback: request failed: %s", exc)
        return None

    # Strip any chain-of-thought blocks some models emit, then take the
    # first meaningful line.
    out = re.sub(r"<think>.*?</think>", "", out, flags=re.DOTALL | re.IGNORECASE)
    line = next((l.strip() for l in out.splitlines() if l.strip()), "")
    line = line.strip().strip('"').strip("`").rstrip(".!?")
    if not line or line.upper() == "NONE" or len(line) > 200:
        return None
    return line


def ask(question: str, max_sentences: int = 2) -> str | None:
    """
    Answer a general question with the LOCAL model, in a couple of spoken
    sentences. Returns None if Ollama is unavailable or errors — callers then
    fall back (e.g. to a web search). Fully offline; no cloud.
    """
    question = (question or "").strip()
    if not question or not is_available():
        return None
    system = (f"You are Echo, a concise voice assistant. Answer the user's "
              f"question in at most {max_sentences} short spoken sentences. "
              f"Plain text only — no markdown, lists, or preamble. If unsure, "
              f"say you're not sure.")
    body = json.dumps({
        "model": OLLAMA_MODEL,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": question}],
        "stream": False, "think": False, "keep_alive": _KEEP_ALIVE,
        "options": {"temperature": 0.2, "num_predict": 160},
    }).encode("utf-8")
    try:
        req = urllib.request.Request(
            OLLAMA_URL + "/api/chat", data=body,
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        out = (data.get("message", {}) or {}).get("content", "") or ""
    except Exception as exc:
        logger.debug("llm_fallback.ask failed: %s", exc)
        return None
    out = re.sub(r"<think>.*?</think>", "", out, flags=re.DOTALL | re.IGNORECASE)
    out = out.strip().strip('"')
    return out or None


def prewarm() -> None:
    """
    Load the model into memory in the background so the first real fallback is
    fast (not a cold ~10-15s load). Safe no-op if Ollama is unavailable.
    """
    import threading

    def _warm():
        if is_available():
            map_to_command("open chrome")  # discard result; just warms the model
            logger.info("llm_fallback: model pre-warmed (%s)", OLLAMA_MODEL)

    threading.Thread(target=_warm, daemon=True, name="llm-prewarm").start()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("Ollama available:", is_available())
    for phrase in ["fire up my browser",
                   "I wanna hear some lofi beats",
                   "shoot a text to mom that I'll be late",
                   "how much is forty seven times nineteen",
                   "the weather is nice today"]:
        print(f"  {phrase!r:45} -> {map_to_command(phrase)!r}")
