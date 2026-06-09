"""
TTS — threaded so it never blocks the main loop.
Uses pyttsx3 → Windows SAPI (built-in, no internet required).
"""
from __future__ import annotations

import threading
import queue

_q: queue.Queue[str | None] = queue.Queue()
_engine = None
_thread: threading.Thread | None = None


def _worker():
    global _engine
    import pyttsx3
    _engine = pyttsx3.init()

    # Pick a natural English voice
    voices = _engine.getProperty("voices")
    preferred = [v for v in voices if "david" in v.name.lower() or "mark" in v.name.lower()]
    if preferred:
        _engine.setProperty("voice", preferred[0].id)
    elif voices:
        _engine.setProperty("voice", voices[0].id)

    _engine.setProperty("rate", 175)     # words per minute
    _engine.setProperty("volume", 0.95)

    while True:
        text = _q.get()
        if text is None:
            break
        _engine.say(text)
        _engine.runAndWait()


def start():
    global _thread
    _thread = threading.Thread(target=_worker, daemon=True, name="nirmiq-tts")
    _thread.start()


def speak(text: str):
    """Non-blocking: enqueue text for TTS."""
    # Clear any pending speech so new response isn't delayed
    while not _q.empty():
        try:
            _q.get_nowait()
        except queue.Empty:
            break
    _q.put(text)


def stop():
    _q.put(None)
