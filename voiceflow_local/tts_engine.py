"""
tts_engine.py - Non-blocking TTS (text-to-speech) voice feedback engine

Uses Windows SAPI via pyttsx3 — fully offline, zero model download, ~3 MB RAM.

Design:
  - All speech is queued and spoken on a single daemon thread
  - Calling speak() never blocks the main/audio thread
  - Interrupt support: speak_interrupt() clears the queue and speaks immediately
  - Graceful fallback: if pyttsx3 is not installed, all calls are silent no-ops

Usage:
    tts = TTSEngine()
    tts.start()
    tts.speak("Opening WhatsApp...")
    tts.speak_interrupt("Timer done!")   # clears queue, speaks now
    tts.stop()
"""

import queue
import threading
import logging
from typing import Optional

logger = logging.getLogger(__name__)

_SENTINEL = object()   # signals the worker thread to exit


class TTSEngine:
    """
    Thread-safe, non-blocking text-to-speech engine.

    All public methods are safe to call from any thread.
    """

    def __init__(
        self,
        rate: int = 175,          # words per minute (150=slow, 200=fast)
        volume: float = 0.95,     # 0.0 – 1.0
        voice_index: int = 0,     # 0 = first available voice (usually English)
    ):
        self._rate = rate
        self._volume = volume
        self._voice_index = voice_index

        self._queue: queue.Queue = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._engine = None       # pyttsx3 engine — created inside worker thread
        self._available = False
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the TTS worker thread."""
        if self._thread and self._thread.is_alive():
            return

        self._thread = threading.Thread(
            target=self._worker,
            name="TTSWorker",
            daemon=True,
        )
        self._thread.start()
        logger.info("TTSEngine: started")

    def stop(self) -> None:
        """Signal the worker to stop and wait briefly."""
        self._queue.put(_SENTINEL)
        if self._thread:
            self._thread.join(timeout=2.0)
        logger.info("TTSEngine: stopped")

    # ------------------------------------------------------------------
    # Public speech API
    # ------------------------------------------------------------------

    def speak(self, text: str) -> None:
        """
        Queue text to be spoken. Non-blocking.
        If TTS is unavailable, silently does nothing.
        """
        if not text or not text.strip():
            return
        self._queue.put(("speak", text.strip()))
        logger.debug("TTS queued: %r", text[:60])

    def speak_interrupt(self, text: str) -> None:
        """
        Clear the queue and speak this text immediately (after any
        currently-running utterance finishes — pyttsx3 can't mid-word stop).
        """
        if not text or not text.strip():
            return
        # Drain pending items
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break
        self._queue.put(("speak", text.strip()))

    @property
    def is_available(self) -> bool:
        return self._available

    # ------------------------------------------------------------------
    # Worker
    # ------------------------------------------------------------------

    def _worker(self) -> None:
        """Runs entirely on the TTS daemon thread."""
        # pyttsx3's SAPI5 driver talks to Windows COM. On a background thread
        # COM may not be initialized for this apartment, which fails with
        # "CoInitialize has not been called". Initialize it explicitly so
        # voice feedback works regardless of thread startup ordering.
        _com_inited = False
        try:
            import pythoncom
            pythoncom.CoInitialize()
            _com_inited = True
        except Exception:
            try:
                import comtypes
                comtypes.CoInitialize()
                _com_inited = True
            except Exception:
                pass  # fall through — pyttsx3 may still self-init on some setups

        try:
            import pyttsx3
            engine = pyttsx3.init()
            engine.setProperty("rate", self._rate)
            engine.setProperty("volume", self._volume)

            voices = engine.getProperty("voices")
            if voices and self._voice_index < len(voices):
                engine.setProperty("voice", voices[self._voice_index].id)

            self._engine = engine
            self._available = True
            logger.info(
                "TTSEngine: pyttsx3 ready — rate=%d vol=%.2f voice=%s",
                self._rate, self._volume,
                voices[self._voice_index].name if voices else "default",
            )
        except ImportError:
            logger.warning(
                "TTSEngine: pyttsx3 not installed — voice feedback disabled. "
                "Install with: pip install pyttsx3"
            )
            self._available = False
            return
        except Exception as exc:
            logger.warning("TTSEngine: init failed: %s", exc)
            self._available = False
            return

        # Main speech loop
        while True:
            try:
                item = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue

            if item is _SENTINEL:
                break

            action, text = item
            if action == "speak":
                try:
                    self._engine.say(text)
                    self._engine.runAndWait()
                except Exception as exc:
                    logger.warning("TTSEngine: speak error: %s", exc)

        # Cleanup
        try:
            if self._engine:
                self._engine.stop()
        except Exception:
            pass
        if _com_inited:
            try:
                import pythoncom
                pythoncom.CoUninitialize()
            except Exception:
                try:
                    import comtypes
                    comtypes.CoUninitialize()
                except Exception:
                    pass
        logger.info("TTSEngine: worker exited")


# ─────────────────────────────────────────────────────────────────────
# Singleton
# ─────────────────────────────────────────────────────────────────────

_tts: Optional[TTSEngine] = None


def get_tts() -> TTSEngine:
    """Return the global TTSEngine singleton (creates + starts if needed)."""
    global _tts
    if _tts is None:
        _tts = TTSEngine()
        _tts.start()
    return _tts


# ─────────────────────────────────────────────────────────────────────
# Self-test
# ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import time
    logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(message)s")

    tts = TTSEngine()
    tts.start()
    time.sleep(0.5)   # give thread a moment to init

    if tts.is_available:
        print("TTS available — testing speech...")
        tts.speak("Hello, I am Echo. Your Jarvis-style voice assistant.")
        time.sleep(0.5)
        tts.speak("I can open apps, play music, send messages, and access your files.")
        time.sleep(5)
        tts.speak_interrupt("Interrupt test — this should play immediately.")
        time.sleep(3)
    else:
        print("TTS not available — install pyttsx3: pip install pyttsx3")

    tts.stop()
    print("Done.")
