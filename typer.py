"""
typer.py - Types transcribed text into the currently active window

Uses clipboard paste (Ctrl+V) as primary method for speed and Unicode safety.
Falls back to pyautogui character-by-character if clipboard is unavailable.
"""

import threading
import queue
import logging
import time

logger = logging.getLogger(__name__)

TYPE_DELAY = 0.05  # seconds to wait before typing (lets focus settle)


def _init_pyautogui() -> bool:
    """Configure pyautogui and return True if available."""
    try:
        import pyautogui
        pyautogui.FAILSAFE = False
        pyautogui.PAUSE = 0.0
        return True
    except Exception as exc:
        logger.error("pyautogui unavailable: %s", exc)
        return False


class TextTyper:
    """
    Receives transcribed text and types it into the currently focused window.
    Runs in its own daemon thread so it never blocks audio or transcription.
    """

    def __init__(self, append_space: bool = True, use_clipboard: bool = True):
        self.append_space = append_space
        self.use_clipboard = use_clipboard

        self._queue = queue.Queue()
        self._running = False
        self._thread = None
        self._available = _init_pyautogui()

        if not self._available:
            logger.warning("TextTyper: pyautogui not available — typing disabled")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the typing worker thread."""
        if not self._available:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._worker_loop,
            name="TextTyperWorker",
            daemon=True,
        )
        self._thread.start()
        logger.info("TextTyper started (clipboard=%s)", self.use_clipboard)

    def stop(self) -> None:
        """Stop the typing worker thread."""
        self._running = False
        self._queue.put(None)  # sentinel
        if self._thread is not None:
            self._thread.join(timeout=3)
            self._thread = None

    def type_text(self, text: str) -> None:
        """Enqueue text for typing. Returns immediately (non-blocking)."""
        if not self._available or not text:
            return
        payload = text + " " if self.append_space else text
        self._queue.put(payload)
        logger.debug("Queued for typing: %r", payload[:60])

    @property
    def is_available(self) -> bool:
        return self._available

    # ------------------------------------------------------------------
    # Worker
    # ------------------------------------------------------------------

    def _worker_loop(self) -> None:
        while self._running:
            try:
                text = self._queue.get(timeout=1.0)
            except queue.Empty:
                continue
            if text is None:
                break
            self._do_type(text)

    def _do_type(self, text: str) -> None:
        """Wait for focus to settle, then inject keystrokes."""
        time.sleep(TYPE_DELAY)
        try:
            if self.use_clipboard:
                self._type_via_clipboard(text)
            else:
                self._type_via_pyautogui(text)
        except Exception as exc:
            logger.error("Typing error: %s", exc, exc_info=True)

    def _type_via_clipboard(self, text: str) -> None:
        """Paste via Ctrl+V — fastest method, fully Unicode safe on Windows."""
        import pyautogui
        import pyperclip

        try:
            original = pyperclip.paste()
        except Exception:
            original = ""

        try:
            pyperclip.copy(text)
            time.sleep(0.02)
            pyautogui.hotkey("ctrl", "v")
            time.sleep(0.05)
        finally:
            try:
                pyperclip.copy(original)
            except Exception:
                pass

    def _type_via_pyautogui(self, text: str) -> None:
        """Type character by character — slower but no clipboard dependency."""
        import pyautogui
        pyautogui.write(text, interval=0.01)
