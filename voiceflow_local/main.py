"""
main.py - NirmiqEcho entry point and application controller

Wires together:
  AudioHandler        — microphone capture + WebRTC VAD
  TranscriptionEngine — faster-whisper (offline), accuracy-tuned
  WakeWordDetector    — "Hello Echo" always-on detector (Whisper tiny)
  TextTyper           — clipboard keystroke injection
  PostProcessor       — filler removal, accent corrections
  AccentProfiler      — personalized initial_prompt from voice samples
  NirmiqEchoUI        — tkinter floating window
  HotkeyManager       — global F9 toggle

Architecture:
  - UI runs on main thread
  - Audio, transcription, wake word all run in daemon threads
  - All cross-thread UI updates go via ui.schedule() → queue → main thread tick
  - Wake word flow: standby → "Hello Echo" detected → auto-start listening
                    → silence → auto-stop → return to standby
"""

import os
import threading
import logging
import sys
from pathlib import Path

# Load .env from the project root (Voice-text/) so WHISPER_MODEL, NOISE_REDUCE_STRENGTH etc. apply
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    pass

from utils import setup_logging, log_system_info, HotkeyManager
from audio_handler import AudioHandler
from transcription import TranscriptionEngine
from wake_word import WakeWordDetector
from typer import TextTyper
from post_processor import PostProcessor
from accent_profile import AccentProfiler
from command_processor import CommandProcessor
from ui import NirmiqEchoUI

logger = logging.getLogger(__name__)

TOGGLE_KEY = "f9"

# Voice samples for accent analysis — the project root (where Test*.m4a live),
# resolved relative to this file so it survives folder renames/moves.
VOICE_SAMPLES_DIR = str(Path(__file__).resolve().parent.parent)
VOICE_SAMPLE_NAMES = [
    "Test 1 voice.m4a",
    "Test 2.m4a",
    "Test 3.m4a",
    "Test 4.m4a",
]


class NirmiqEchoApp:
    """
    Central controller that owns all subsystems and coordinates their interactions.

    Lifecycle:
        1. __init__  — create subsystem objects (nothing started yet)
        2. run()     — show UI immediately, load models in background
        3. shutdown() — clean up all threads and resources

    Echo Mode (wake word flow):
        DISABLED : manual F9 / button only (original behaviour)
        ENABLED  : app sits in standby, activates on "Hello Echo",
                   auto-stops after silence, returns to standby
    """

    def __init__(self):
        self.audio_handler = None
        self.transcription_engine = None
        self.wake_word_detector = None
        self.text_typer = None
        self.post_processor = None
        self.accent_profiler = None
        self.command_processor = None
        self.tts_engine = None
        self.ui = None

        self._hotkeys = HotkeyManager()
        self._listening = False
        self._echo_mode = False      # wake word mode on/off
        # Plug-and-play: start listening the moment the model is ready, so the
        # user never has to press F9 first. Override with AUTORUN=0 in .env.
        self._autorun = os.getenv("AUTORUN", "1") != "0"

    # ------------------------------------------------------------------
    # Startup
    # ------------------------------------------------------------------

    def run(self) -> None:
        log_system_info()

        # --- TTS Engine (start first — other subsystems use it) ---
        try:
            from tts_engine import TTSEngine
            self.tts_engine = TTSEngine(rate=175, volume=0.95)
            self.tts_engine.start()
            logger.info("TTS engine started")
        except Exception as exc:
            logger.warning("TTS engine failed to start: %s", exc)
            self.tts_engine = None

        # --- Accent profiler (load cached profile instantly) ---
        self.accent_profiler = AccentProfiler()

        # --- Post-processor ---
        self.post_processor = PostProcessor(
            remove_fillers=True,
            apply_accent_corrections=True,
            auto_punctuate=True,
            capitalize=True,
        )

        # --- Command processor (Jarvis) ---
        self.command_processor = CommandProcessor(
            on_mode_change=self.set_mode,
            on_stop_echo=self.disable_echo_mode,
            on_clear_transcript=lambda: self.ui.schedule("clear_transcript", None) if self.ui else None,
            on_status_change=self._on_transcription_status,
            on_feedback=self._on_command_feedback,
        )

        # --- Audio handler ---
        # sensitivity=1: permissive enough to catch quiet speech while still
        # rejecting most background noise. User can raise to 2 in Settings if
        # getting too many false triggers.
        self.audio_handler = AudioHandler(
            sensitivity=1,
            on_status_change=self._on_audio_status,
        )

        # --- Transcription engine (with accent initial_prompt) ---
        self.transcription_engine = TranscriptionEngine(
            speech_queue=self.audio_handler.speech_queue,
            on_result=self._on_result,
            on_status_change=self._on_transcription_status,
            language="en",
            initial_prompt=self.accent_profiler.initial_prompt,
        )

        # --- Wake word detector ---
        self.wake_word_detector = WakeWordDetector(
            on_wake=self._on_wake_word,
            on_status_change=self._on_wake_status,
        )

        # --- Text typer ---
        self.text_typer = TextTyper(append_space=True, use_clipboard=True)
        self.text_typer.start()

        # --- UI ---
        self.ui = NirmiqEchoUI(app=self)

        # --- Global hotkey ---
        self._hotkeys.register(TOGGLE_KEY, self._toggle)

        # --- Background: load main model + tiny model + accent analysis ---
        threading.Thread(
            target=self._startup_sequence,
            name="StartupLoader",
            daemon=True,
        ).start()

        logger.info("Starting UI main loop")
        self.ui.run()  # blocks until window closed

    def _startup_sequence(self) -> None:
        """Load models and run accent analysis in the background."""
        self.ui.schedule("set_status", "loading")
        self.ui.schedule("set_model_info", "Loading Whisper model…")

        # 1. Load main transcription model
        try:
            self.transcription_engine.load_model()
            self.transcription_engine.start()
            self.ui.schedule("set_model_info", self.transcription_engine.model_info)
            self.ui.schedule("set_status", "ready")
            logger.info("Main model ready: %s", self.transcription_engine.model_info)
        except Exception as exc:
            logger.error("Main model loading failed: %s", exc, exc_info=True)
            self.ui.schedule("set_status", "error")
            self.ui.schedule("set_model_info", "Error loading model")
            self.ui.schedule("show_error",
                f"Failed to load Whisper model:\n\n{exc}\n\n"
                "Make sure faster-whisper is installed:\n"
                "  pip install faster-whisper")
            return

        # 2. Load tiny wake word model (in parallel with accent analysis)
        tiny_thread = threading.Thread(
            target=self._load_wake_word_model,
            name="WakeWordLoader",
            daemon=True,
        )
        tiny_thread.start()

        # 3. Run accent analysis if no profile exists yet
        accent_thread = threading.Thread(
            target=self._run_accent_analysis,
            name="AccentAnalysis",
            daemon=True,
        )
        accent_thread.start()

        # 3b. Pre-warm the local-LLM fallback (if Ollama is running) so the
        #     first "understand anything" command isn't a cold model load.
        try:
            import llm_fallback
            llm_fallback.prewarm()
        except Exception as exc:
            logger.debug("llm_fallback prewarm skipped: %s", exc)

        # 4. Auto-start if configured (plug-and-play default)
        if self._autorun:
            self.start_listening()
            if self.tts_engine and self.tts_engine.is_available:
                self.tts_engine.speak(
                    "Nirmiq Echo online and listening. Just speak your command.")
        elif self.tts_engine and self.tts_engine.is_available:
            self.tts_engine.speak("Nirmiq Echo ready. Press F9 to start listening.")

    def _load_wake_word_model(self) -> None:
        """Load Whisper tiny for wake word detection."""
        try:
            self.ui.schedule("set_model_info",
                             f"{self.transcription_engine.model_info}  ·  loading wake…")
            self.wake_word_detector.load_model()
            self.ui.schedule("set_model_info", self.transcription_engine.model_info)
            logger.info("Wake word model ready")
            # If echo mode was enabled before model loaded, start now
            if self._echo_mode:
                self._start_echo_mode()
        except Exception as exc:
            logger.warning("Wake word model failed to load: %s", exc)
            self.ui.schedule("show_error",
                f"Wake word model failed to load:\n{exc}\n\n"
                "Echo Mode will be unavailable. Manual F9 still works.")

    def _run_accent_analysis(self) -> None:
        """
        Analyse user's voice samples if no profile exists yet.
        On success, hot-update the transcription engine's initial_prompt.
        """
        if self.accent_profiler.is_analyzed:
            logger.info("AccentAnalysis: existing profile found, skipping re-analysis")
            return

        sample_files = [
            str(Path(VOICE_SAMPLES_DIR) / name)
            for name in VOICE_SAMPLE_NAMES
            if (Path(VOICE_SAMPLES_DIR) / name).exists()
        ]

        if not sample_files:
            logger.info("AccentAnalysis: no sample files found")
            return

        logger.info("AccentAnalysis: analysing %d voice samples…", len(sample_files))
        self.ui.schedule("set_model_info", "Analysing your voice samples…")

        ok = self.accent_profiler.analyze(sample_files)

        if ok:
            # Hot-update the transcription engine
            self.transcription_engine.update_prompt(self.accent_profiler.initial_prompt)
            self.ui.schedule("set_model_info", self.transcription_engine.model_info)
            logger.info("AccentAnalysis: prompt updated in TranscriptionEngine")
        else:
            self.ui.schedule("set_model_info", self.transcription_engine.model_info)

    # ------------------------------------------------------------------
    # Listening control
    # ------------------------------------------------------------------

    def start_listening(self) -> None:
        if self._listening:
            return
        if not self.transcription_engine.is_ready:
            return
        try:
            # Pause wake word detector while we're actively recording
            if self.wake_word_detector and self.wake_word_detector.is_ready:
                self.wake_word_detector.pause()

            self.audio_handler.start()
            self._listening = True
            self.ui.schedule("set_listening", True)
            logger.info("Listening started")
        except RuntimeError as exc:
            logger.error("Could not start listening: %s", exc)
            self.ui.schedule("show_error", str(exc))
            # Resume wake detector since we failed to start
            if self.wake_word_detector and self.wake_word_detector.is_ready:
                self.wake_word_detector.resume()

    def stop_listening(self) -> None:
        if not self._listening:
            return
        self.audio_handler.stop()
        self._listening = False
        self.ui.schedule("set_listening", False)

        # Return to standby or ready depending on echo mode
        if self._echo_mode and self.wake_word_detector and \
                self.wake_word_detector.is_ready:
            self.wake_word_detector.resume()
            self.ui.schedule("set_status", "standby")
        else:
            self.ui.schedule("set_status", "ready")

        logger.info("Listening stopped")

    def _toggle(self) -> None:
        """Toggle listening — called by F9 from any thread."""
        if self._listening:
            self.stop_listening()
        else:
            self.start_listening()

    # ------------------------------------------------------------------
    # Echo Mode (wake word)
    # ------------------------------------------------------------------

    def enable_echo_mode(self) -> None:
        """Enable 'Hello Echo' wake word activation."""
        self._echo_mode = True
        if self.wake_word_detector and self.wake_word_detector.is_ready:
            self._start_echo_mode()
        else:
            logger.info("Echo Mode queued — wake word model still loading")
        self.ui.schedule("set_echo_mode", True)

    def disable_echo_mode(self) -> None:
        """Disable wake word; return to manual F9 mode."""
        self._echo_mode = False
        if self.wake_word_detector:
            self.wake_word_detector.stop()
        # Rebuild fresh detector for next enable
        self.wake_word_detector = WakeWordDetector(
            on_wake=self._on_wake_word,
            on_status_change=self._on_wake_status,
        )
        self.ui.schedule("set_echo_mode", False)
        if not self._listening:
            self.ui.schedule("set_status", "ready")
        logger.info("Echo Mode disabled")

    def _start_echo_mode(self) -> None:
        """Actually start the wake word detector stream."""
        try:
            if not self.wake_word_detector.is_running:
                self.wake_word_detector.start()
            self.ui.schedule("set_status", "standby")
            logger.info("Echo Mode active — say 'Hello Echo' to start")
        except Exception as exc:
            logger.error("Could not start wake word detector: %s", exc)
            self._echo_mode = False
            self.ui.schedule("set_echo_mode", False)
            self.ui.schedule("show_error",
                f"Could not start Echo Mode:\n{exc}")

    def set_sensitivity(self, value: int) -> None:
        if self.audio_handler:
            self.audio_handler.set_sensitivity(value)

    def set_mode(self, mode: str) -> None:
        """Switch post-processing mode: 'note', 'message', 'search', 'default'."""
        if self.post_processor:
            self.post_processor.set_mode(mode)
            logger.info("Mode set to: %s", mode)

    # ------------------------------------------------------------------
    # Callbacks from background threads
    # ------------------------------------------------------------------

    def _on_wake_word(self) -> None:
        """Called from WakeWordDetector thread when 'Hello Echo' is heard."""
        logger.info("Wake word triggered — activating listening")
        self.start_listening()

    def _on_wake_status(self, status: str) -> None:
        if self.ui:
            self.ui.schedule("set_status", status)

    def _on_audio_status(self, status: str) -> None:
        if self.ui:
            self.ui.schedule("set_status", status)

    def _on_transcription_status(self, status: str) -> None:
        if self.ui:
            self.ui.schedule("set_status", status)

    def _on_result(self, text: str) -> None:
        # Apply post-processing pipeline
        if self.post_processor:
            cleaned = self.post_processor.clean(text)
        else:
            cleaned = text

        # Drop hallucinated / empty results
        if not cleaned:
            logger.debug("Result dropped (empty/hallucinated): %r", text[:60])
            return

        logger.info("Result: %s", cleaned)

        # Route through Jarvis command engine
        if self.command_processor:
            cmd_result = self.command_processor.process(cleaned)
            if cmd_result.is_command:
                # Execute command silently — don't type it
                self.command_processor.execute(cmd_result)
                # Show feedback in transcript for visibility
                if cmd_result.feedback and self.ui:
                    self.ui.schedule("append_transcript",
                                     f"[Cmd] {cmd_result.feedback}")
                return
            # "type hello world" → type only "hello world", not the word "type"
            if cmd_result.action == "force_type":
                cleaned = cmd_result.args.get("text", cleaned)

        # Not a command — type into focused app and add to transcript
        if self.text_typer and self.text_typer.is_available:
            self.text_typer.type_text(cleaned)
            if self.command_processor:
                self.command_processor.record_typed(cleaned)
        if self.ui:
            self.ui.schedule("append_transcript", cleaned)

    def _on_command_feedback(self, msg: str) -> None:
        """Show brief command execution feedback in the UI status bar."""
        if self.ui:
            self.ui.schedule("set_status_text", msg)
            # Restore the real status after 2 seconds
            import threading
            def _restore():
                import time
                time.sleep(2)
                if self.ui:
                    if self._listening:
                        self.ui.schedule("set_status", "listening")
                    elif self._echo_mode:
                        self.ui.schedule("set_status", "standby")
                    else:
                        self.ui.schedule("set_status", "ready")
            threading.Thread(target=_restore, daemon=True).start()

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    def shutdown(self) -> None:
        logger.info("Shutting down NirmiqEcho…")
        self._hotkeys.unregister_all()

        if self._listening and self.audio_handler:
            try:
                self.audio_handler.stop()
            except Exception as exc:
                logger.warning("Error stopping audio: %s", exc)

        if self.wake_word_detector:
            try:
                self.wake_word_detector.stop()
            except Exception as exc:
                logger.warning("Error stopping wake word: %s", exc)

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

        if self.tts_engine:
            try:
                self.tts_engine.stop()
            except Exception as exc:
                logger.warning("Error stopping TTS: %s", exc)

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
