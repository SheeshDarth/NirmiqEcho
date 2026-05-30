"""
main.py - NirmiqEcho entry point and application controller

Wires together:
  AudioHandler       — microphone capture + WebRTC VAD
  TranscriptionEngine — faster-whisper (offline)
  TextTyper          — clipboard keystroke injection
  NirmiqEchoUI       — tkinter floating window
  HotkeyManager      — global F9 toggle

Architecture: all heavy work runs in daemon threads;
the UI runs on the main thread and receives updates via a thread-safe queue.
"""

import threading
import logging
import sys

from utils import setup_logging, log_system_info, HotkeyManager
from audio_handler import AudioHandler
from transcription import TranscriptionEngine
from typer import TextTyper
from ui import NirmiqEchoUI

logger = logging.getLogger(__name__)

TOGGLE_KEY = "f9"


class NirmiqEchoApp:
    """
    Central controller that owns all subsystems and coordinates their interactions.

    Lifecycle:
        1. __init__  — create subsystem objects (nothing started yet)
        2. run()     — show UI immediately, load model in background
        3. shutdown() — clean up all threads and resources
    """

    def __init__(self):
        self.audio_handler = None
        self.transcription_engine = None
        self.text_typer = None
        self.ui = None
        self._hotkeys = HotkeyManager()
        self._listening = False
        self._autorun = False  # set by SettingsModal

    # ------------------------------------------------------------------
    # Startup
    # ------------------------------------------------------------------

    def run(self) -> None:
        log_system_info()

        self.audio_handler = AudioHandler(
            sensitivity=2,
            on_status_change=self._on_audio_status,
        )


        self.transcription_engine = TranscriptionEngine(
            speech_queue=self.audio_handler.speech_queue,
            on_result=self._on_result,
            on_status_change=self._on_transcription_status,
        )

        self.text_typer = TextTyper(append_space=True, use_clipboard=True)
        self.text_typer.start()

        self.ui = NirmiqEchoUI(app=self)

        self._hotkeys.register(TOGGLE_KEY, self._toggle)

        # Load model in background so the UI appears immediately
        # After model loads, auto-start if SettingsModal enabled it
        threading.Thread(
            target=self._load_model,
            name="ModelLoader",
            daemon=True,
        ).start()

        logger.info("Starting UI main loop")
        self.ui.run()  # blocks until the window is closed

    def _load_model(self) -> None:
        self.ui.schedule("set_status", "loading")
        self.ui.schedule("set_model_info", "Loading model…")
        try:
            self.transcription_engine.load_model()
            self.transcription_engine.start()
            self.ui.schedule("set_model_info", self.transcription_engine.model_info)
            self.ui.schedule("set_status", "ready")
            logger.info("Model ready: %s", self.transcription_engine.model_info)
            if self._autorun:
                self.start_listening()
        except Exception as exc:
            logger.error("Model loading failed: %s", exc, exc_info=True)
            self.ui.schedule("set_status", "error")
            self.ui.schedule("set_model_info", f"Error loading model")
            self.ui.schedule("show_error",
                f"Failed to load Whisper model:\n\n{exc}\n\n"
                "Make sure faster-whisper is installed:\n"
                "  pip install faster-whisper")

    # ------------------------------------------------------------------
    # Listen control (called from UI buttons and the F9 hotkey)
    # ------------------------------------------------------------------

    def start_listening(self) -> None:
        if self._listening:
            return
        if not self.transcription_engine.is_ready:
            self.ui.schedule("show_error", "Please wait — the model is still loading.")
            return
        try:
            self.audio_handler.start()
            self._listening = True
            self.ui.schedule("set_listening", True)
            logger.info("Listening started")
        except RuntimeError as exc:
            logger.error("Could not start listening: %s", exc)
            self.ui.schedule("show_error", str(exc))

    def stop_listening(self) -> None:
        if not self._listening:
            return
        self.audio_handler.stop()
        self._listening = False
        self.ui.schedule("set_listening", False)
        self.ui.schedule("set_status", "ready")
        logger.info("Listening stopped")

    def _toggle(self) -> None:
        """Toggle listening — called by F9 from any thread."""
        if self._listening:
            self.stop_listening()
        else:
            self.start_listening()

    def set_sensitivity(self, value: int) -> None:
        if self.audio_handler:
            self.audio_handler.set_sensitivity(value)

    # ------------------------------------------------------------------
    # Callbacks from background threads
    # (must only call self.ui.schedule — never touch Tkinter directly)
    # ------------------------------------------------------------------

    def _on_audio_status(self, status: str) -> None:
        if self.ui:
            self.ui.schedule("set_status", status)

    def _on_transcription_status(self, status: str) -> None:
        if self.ui:
            self.ui.schedule("set_status", status)

    def _on_result(self, text: str) -> None:
        logger.info("Result: %s", text)
        if self.ui:
            self.ui.schedule("append_transcript", text)
        if self.text_typer and self.text_typer.is_available:
            self.text_typer.type_text(text)

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    def shutdown(self) -> None:
        logger.info("Shutting down NirmiqEcho…")
        self._hotkeys.unregister_all()

        if self._listening:
            try:
                self.audio_handler.stop()
            except Exception as exc:
                logger.warning("Error stopping audio: %s", exc)

        if self.transcription_engine:
            try:
                self.transcription_engine.stop()
            except Exception as exc:
                logger.warning("Error stopping transcription: %s", exc)

        if self.text_typer:
            try:
                self.text_typer.stop()
            except Exception as exc:
                logger.warning("Error stopping typer: %s", exc)

        logger.info("Shutdown complete")


# ------------------------------------------------------------------
# Entry point
# ------------------------------------------------------------------

def main():
    setup_logging(logging.INFO)

    if sys.version_info < (3, 10):
        print("ERROR: NirmiqEcho requires Python 3.10 or newer.")
        print(f"       Current version: {sys.version}")
        sys.exit(1)

    missing = []
    for pkg in ("sounddevice", "numpy", "webrtcvad", "faster_whisper",
                "pyautogui", "keyboard"):
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg.replace("_", "-"))

    if missing:
        print("\n=== Missing dependencies ===")
        print(f"  pip install {' '.join(missing)}\n")
        sys.exit(1)

    app = NirmiqEchoApp()
    try:
        app.run()
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        app.shutdown()
    except Exception as exc:
        logger.critical("Fatal error: %s", exc, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
