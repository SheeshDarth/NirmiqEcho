# Codex Implementation Document - VoiceFlow Local

This document contains the complete, production-ready source code for all components of **VoiceFlow Local**. These files are fully realized with zero placeholder text or empty classes, making them completely executable.

---

## 📂 Source Code Catalog

### 1. `main.py`
The central controller that bootstraps the UI, initializes threads, and coordinates audio, transcription, typing, and hotkey subsystems.
*   **File Path**: [main.py](file:///C:/Users/Siddharth/Desktop/Voice-text/voiceflow_local/main.py)

```python
"""
main.py - VoiceFlow Local entry point and application controller

Wires together:
- AudioHandler  (microphone + VAD)
- TranscriptionEngine (faster-whisper)
- TextTyper     (keystroke injection)
- VoiceFlowUI   (tkinter window)
- HotkeyManager (global F9 toggle)

Architecture: all heavy work runs in daemon threads; the UI runs on the
main thread and receives updates via a thread-safe queue.
"""

import threading
import logging
import sys
import time
from pathlib import Path

from utils import setup_logging, log_system_info, HotkeyManager
from audio_handler import AudioHandler
from transcription import TranscriptionEngine
from typer import TextTyper
from ui import VoiceFlowUI

logger = logging.getLogger(__name__)

HOTKEY_TOGGLE = "f9"


class VoiceFlowApp:
    """
    Central controller that owns all subsystems and mediates their interactions.

    Lifecycle:
        1. __init__  — create subsystems, do not start anything yet
        2. run()     — load model in background, then open the UI (blocking)
        3. shutdown() — stop all threads, release resources
    """

    def __init__(self):
        self.audio_handler: AudioHandler | None = None
        self.transcription_engine: TranscriptionEngine | None = None
        self.text_typer: TextTyper | None = None
        self.ui: VoiceFlowUI | None = None
        self._hotkey_manager = HotkeyManager()
        self._shutdown_event = threading.Event()
        self._listening = False

    # ------------------------------------------------------------------
    # Startup
    # ------------------------------------------------------------------

    def run(self) -> None:
        """
        Main entry point:
          1. Build subsystems
          2. Show UI immediately (before model loads)
          3. Load Whisper model in background thread
          4. Register global hotkeys
          5. Block on tkinter event loop
        """
        log_system_info()

        # Build audio handler (no stream opened yet)
        self.audio_handler = AudioHandler(
            sensitivity=2,
            on_status_change=self._on_audio_status,
        )

        # Build transcription engine (model not loaded yet)
        self.transcription_engine = TranscriptionEngine(
            speech_queue=self.audio_handler.speech_queue,
            on_result=self._on_transcription_result,
            on_status_change=self._on_transcription_status,
        )

        # Build text typer
        self.text_typer = TextTyper(append_space=True, use_clipboard=True)
        self.text_typer.start()

        # Build UI (does not block — mainloop called below)
        self.ui = VoiceFlowUI(app_controller=self)

        # Register the toggle hotkey
        self._hotkey_manager.register(HOTKEY_TOGGLE, self._toggle_listening)

        # Load model asynchronously so the UI appears immediately
        model_thread = threading.Thread(
            target=self._load_model_async,
            name="ModelLoader",
            daemon=True,
        )
        model_thread.start()

        logger.info("Starting UI main loop")
        self.ui.run()  # BLOCKS until window is closed

    def _load_model_async(self) -> None:
        """Load the Whisper model without blocking the UI."""
        self.ui.schedule("set_status", "loading")
        self.ui.schedule("set_model_info", "Loading model, please wait…")

        try:
            self.transcription_engine.load_model()
            self.transcription_engine.start()

            info = self.transcription_engine.model_info
            self.ui.schedule("set_model_info", info)
            self.ui.schedule("set_status", "ready")
            logger.info("Model ready: %s", info)

        except Exception as exc:
            logger.error("Model loading failed: %s", exc, exc_info=True)
            self.ui.schedule("set_status", "error")
            self.ui.schedule("set_model_info", f"Error: {exc}")
            self.ui.schedule("show_error",
                f"Failed to load Whisper model:\n\n{exc}\n\n"
                "Make sure faster-whisper is installed:\n"
                "pip install faster-whisper"
            )

    # ------------------------------------------------------------------
    # Listening control (called from UI buttons and hotkey)
    # ------------------------------------------------------------------

    def start_listening(self) -> None:
        """Open the microphone and start VAD."""
        if self._listening:
            return
        if not self.transcription_engine.is_ready:
            self.ui.schedule("show_error",
                "Please wait — the model is still loading.")
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
        """Stop microphone capture."""
        if not self._listening:
            return
        self.audio_handler.stop()
        self._listening = False
        self.ui.schedule("set_listening", False)
        self.ui.schedule("set_status", "ready")
        logger.info("Listening stopped")

    def _toggle_listening(self) -> None:
        """Toggle listening on/off (called by F9 hotkey from non-main thread)."""
        if self._listening:
            self.stop_listening()
        else:
            self.start_listening()

    def set_sensitivity(self, sensitivity: int) -> None:
        """Update VAD sensitivity on both the handler and the engine."""
        if self.audio_handler:
            self.audio_handler.set_sensitivity(sensitivity)
        logger.info("Sensitivity updated to %d", sensitivity)

    # ------------------------------------------------------------------
    # Callbacks from background threads
    # (must only schedule UI updates — never call tkinter directly)
    # ------------------------------------------------------------------

    def _on_audio_status(self, status: str) -> None:
        """Called by AudioHandler from the audio callback thread."""
        if self.ui:
            self.ui.schedule("set_status", status)

    def _on_transcription_status(self, status: str) -> None:
        """Called by TranscriptionEngine from the worker thread."""
        if self.ui:
            self.ui.schedule("set_status", status)

    def _on_transcription_result(self, text: str) -> None:
        """
        Called by TranscriptionEngine when a segment is transcribed.
        Dispatches to the UI and triggers keystroke injection.
        """
        logger.info("Result: %s", text)
        if self.ui:
            self.ui.schedule("append_transcript", text)
        if self.text_typer and self.text_typer.is_available:
            self.text_typer.type_text(text)

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    def shutdown(self) -> None:
        """Cleanly stop all subsystems. Called when the window is closed."""
        logger.info("Shutting down VoiceFlow…")
        self._shutdown_event.set()

        self._hotkey_manager.unregister_all()

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

    # Verify Python version
    if sys.version_info < (3, 10):
        print("ERROR: VoiceFlow Local requires Python 3.10 or newer.")
        print(f"       Current version: {sys.version}")
        sys.exit(1)

    # Verify critical dependencies before starting
    missing = []
    for pkg in ("sounddevice", "numpy", "webrtcvad", "faster_whisper",
                "pyautogui", "keyboard"):
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg)

    if missing:
        print("\n=== Missing dependencies ===")
        print("Please install the missing packages:\n")
        pkgs = " ".join(m.replace("_", "-") for m in missing)
        print(f"  pip install {pkgs}\n")
        sys.exit(1)

    app = VoiceFlowApp()
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
```

---

### 2. `audio_handler.py`
Interfaces with sounddevice, monitors microphone volume, and parses frame buffers using `webrtcvad`.
*   **File Path**: [audio_handler.py](file:///C:/Users/Siddharth/Desktop/Voice-text/voiceflow_local/audio_handler.py)

```python
"""
audio_handler.py - Microphone capture and Voice Activity Detection (VAD)

Handles:
- Microphone stream using sounddevice
- Real-time VAD using webrtcvad
- Silence detection and speech segment extraction
- Thread-safe audio buffer management
"""

import threading
import queue
import logging
import numpy as np
import sounddevice as sd
import webrtcvad

logger = logging.getLogger(__name__)


# VAD requires audio at specific sample rates
VAD_SAMPLE_RATE = 16000  # 16 kHz required by webrtcvad

# webrtcvad processes frames of 10ms, 20ms, or 30ms
FRAME_DURATION_MS = 30  # 30ms frames for better accuracy
FRAME_SIZE = int(VAD_SAMPLE_RATE * FRAME_DURATION_MS / 1000)  # samples per frame

# Silence detection settings
SILENCE_THRESHOLD_FRAMES = 20   # number of consecutive silent frames before stopping
SPEECH_THRESHOLD_FRAMES = 3     # number of voiced frames to confirm speech started
MIN_SPEECH_FRAMES = 5           # minimum frames to consider a valid utterance
MAX_UTTERANCE_SECONDS = 30      # maximum single utterance length


class AudioHandler:
    """
    Captures microphone audio and performs real-time voice activity detection.

    Speech segments are extracted and placed into a queue for the
    transcription engine to consume.
    """

    def __init__(self, sensitivity: int = 2, on_status_change=None):
        """
        Args:
            sensitivity: VAD aggressiveness (0=least aggressive, 3=most aggressive).
                         Higher values filter out more non-speech noise.
            on_status_change: Callback(status: str) called when detection state changes.
        """
        self.sensitivity = max(0, min(3, sensitivity))
        self.on_status_change = on_status_change or (lambda s: None)

        self._vad = webrtcvad.Vad(self.sensitivity)
        self._stream = None
        self._running = False
        self._lock = threading.Lock()

        # Queue that holds complete speech segments (as numpy float32 arrays)
        self.speech_queue: queue.Queue = queue.Queue()

        # Internal ring buffer accumulating incoming audio frames
        self._audio_buffer: list[bytes] = []
        self._voiced_frames: list[bytes] = []

        # State machine counters
        self._num_voiced = 0
        self._num_silent = 0
        self._in_speech = False

        # Audio level for UI feedback (0.0 - 1.0)
        self.audio_level: float = 0.0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Open the microphone stream and begin VAD processing."""
        with self._lock:
            if self._running:
                return
            self._running = True

        self._reset_state()
        logger.info("Opening microphone stream at %d Hz", VAD_SAMPLE_RATE)

        try:
            self._stream = sd.RawInputStream(
                samplerate=VAD_SAMPLE_RATE,
                channels=1,
                dtype="int16",
                blocksize=FRAME_SIZE,
                callback=self._audio_callback,
            )
            self._stream.start()
            self.on_status_change("listening")
            logger.info("Microphone stream started")
        except Exception as exc:
            self._running = False
            logger.error("Failed to open microphone: %s", exc)
            raise RuntimeError(f"Could not open microphone: {exc}") from exc

    def stop(self) -> None:
        """Stop microphone capture and close the stream."""
        with self._lock:
            if not self._running:
                return
            self._running = False

        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception as exc:
                logger.warning("Error closing stream: %s", exc)
            finally:
                self._stream = None

        # Flush any in-progress speech segment
        self._flush_speech()
        self.on_status_change("idle")
        logger.info("Microphone stream stopped")

    def set_sensitivity(self, sensitivity: int) -> None:
        """Update VAD sensitivity at runtime (0-3)."""
        self.sensitivity = max(0, min(3, sensitivity))
        self._vad.set_mode(self.sensitivity)
        logger.debug("VAD sensitivity set to %d", self.sensitivity)

    @property
    def is_running(self) -> bool:
        return self._running

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _audio_callback(self, indata: bytes, frames: int, time_info, status) -> None:
        """
        sounddevice callback — called on a dedicated audio thread.
        Must not block or raise exceptions.
        """
        if status:
            logger.debug("Audio stream status: %s", status)

        if not self._running:
            return

        raw_bytes = bytes(indata)

        # Compute audio level for UI visualization
        pcm = np.frombuffer(raw_bytes, dtype=np.int16)
        rms = float(np.sqrt(np.mean(pcm.astype(np.float32) ** 2)))
        self.audio_level = min(1.0, rms / 8000.0)

        try:
            is_speech = self._vad.is_speech(raw_bytes, VAD_SAMPLE_RATE)
        except Exception:
            is_speech = False

        self._process_frame(raw_bytes, is_speech)

    def _process_frame(self, frame: bytes, is_speech: bool) -> None:
        """State machine: accumulate voiced frames, detect utterance boundaries."""
        if is_speech:
            self._num_voiced += 1
            self._num_silent = 0

            if not self._in_speech and self._num_voiced >= SPEECH_THRESHOLD_FRAMES:
                self._in_speech = True
                logger.debug("Speech start detected")
                self.on_status_change("listening_active")

            if self._in_speech:
                self._voiced_frames.append(frame)

                # Safety cap: flush if utterance is too long
                max_frames = int(MAX_UTTERANCE_SECONDS * 1000 / FRAME_DURATION_MS)
                if len(self._voiced_frames) >= max_frames:
                    logger.debug("Max utterance length reached, flushing")
                    self._flush_speech()

        else:
            self._num_silent += 1
            self._num_voiced = 0

            if self._in_speech:
                # Keep buffering during brief silences (padding)
                self._voiced_frames.append(frame)

                if self._num_silent >= SILENCE_THRESHOLD_FRAMES:
                    self._flush_speech()

    def _flush_speech(self) -> None:
        """Convert buffered frames into a float32 PCM array and enqueue it."""
        if not self._voiced_frames:
            self._reset_state()
            return

        if len(self._voiced_frames) < MIN_SPEECH_FRAMES:
            logger.debug("Utterance too short (%d frames), discarding", len(self._voiced_frames))
            self._reset_state()
            return

        combined = b"".join(self._voiced_frames)
        pcm = np.frombuffer(combined, dtype=np.int16).astype(np.float32) / 32768.0

        logger.debug("Enqueuing speech segment: %.2f s", len(pcm) / VAD_SAMPLE_RATE)
        self.speech_queue.put(pcm)
        self.on_status_change("transcribing")
        self._reset_state()

    def _reset_state(self) -> None:
        """Reset the VAD state machine."""
        self._voiced_frames = []
        self._num_voiced = 0
        self._num_silent = 0
        self._in_speech = False

    # ------------------------------------------------------------------
    # Microphone enumeration utility
    # ------------------------------------------------------------------

    @staticmethod
    def list_input_devices() -> list[dict]:
        """Return a list of available input audio devices."""
        devices = []
        for i, dev in enumerate(sd.query_devices()):
            if dev["max_input_channels"] > 0:
                devices.append({"index": i, "name": dev["name"]})
        return devices

    @staticmethod
    def get_default_input_device() -> dict | None:
        """Return the default input device info, or None if none found."""
        try:
            idx = sd.default.device[0]
            if idx is None or idx < 0:
                devices = AudioHandler.list_input_devices()
                return devices[0] if devices else None
            dev = sd.query_devices(idx)
            return {"index": idx, "name": dev["name"]}
        except Exception as exc:
            logger.warning("Could not determine default input device: %s", exc)
            return None
```

---

### 3. `transcription.py`
Instantiates `faster-whisper` dynamically using PyTorch device configurations, transcribing segments in the background.
*   **File Path**: [transcription.py](file:///C:/Users/Siddharth/Desktop/Voice-text/voiceflow_local/transcription.py)

```python
"""
transcription.py - Local offline speech-to-text using faster-whisper

Handles:
- Model loading (CPU int8 / GPU float16 auto-detection)
- Consuming audio segments from the speech queue
- Running transcription in a background thread
- Dispatching results via callback
"""

import threading
import queue
import logging
import time
import numpy as np

logger = logging.getLogger(__name__)


def _detect_compute_device() -> tuple[str, str]:
    """
    Detect whether CUDA is available and return (device, compute_type).

    Returns:
        ("cuda", "float16") if a CUDA-capable GPU is found,
        ("cpu",  "int8")    otherwise.
    """
    try:
        import torch
        if torch.cuda.is_available():
            gpu_name = torch.cuda.get_device_name(0)
            logger.info("CUDA GPU detected: %s", gpu_name)
            return "cuda", "float16"
    except ImportError:
        pass

    try:
        # CTranslate2 can also report CUDA availability without PyTorch
        import ctranslate2
        if ctranslate2.get_cuda_device_count() > 0:
            logger.info("CUDA detected via CTranslate2")
            return "cuda", "float16"
    except Exception:
        pass

    logger.info("No CUDA GPU found — using CPU with int8 quantization")
    return "cpu", "int8"


def _select_model(device: str) -> str:
    """Choose the default Whisper model based on available hardware."""
    if device == "cuda":
        return "large-v3"
    return "medium"


class TranscriptionEngine:
    """
    Pulls audio segments from a queue, transcribes them with faster-whisper,
    and dispatches text results via a callback.

    Runs in its own daemon thread so it never blocks the UI.
    """

    def __init__(
        self,
        speech_queue: queue.Queue,
        on_result,
        on_status_change=None,
        model_size: str | None = None,
        language: str | None = None,
    ):
        """
        Args:
            speech_queue:     Queue[np.ndarray] shared with AudioHandler.
            on_result:        Callback(text: str) called for each transcription.
            on_status_change: Callback(status: str) for UI state updates.
            model_size:       Override the whisper model (e.g. "base", "small").
            language:         Force a language code (e.g. "en"). None = auto-detect.
        """
        self.speech_queue = speech_queue
        self.on_result = on_result
        self.on_status_change = on_status_change or (lambda s: None)
        self.language = language

        self._running = False
        self._thread: threading.Thread | None = None
        self._model = None
        self._model_lock = threading.Lock()

        # Auto-detect hardware
        self.device, self.compute_type = _detect_compute_device()
        self.model_size = model_size or _select_model(self.device)

        logger.info(
            "TranscriptionEngine: model=%s  device=%s  compute=%s  language=%s",
            self.model_size, self.device, self.compute_type,
            self.language or "auto",
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_model(self) -> None:
        """
        Download/load the faster-whisper model.
        Call this once at startup (in a background thread if you want non-blocking).
        """
        from faster_whisper import WhisperModel

        logger.info("Loading faster-whisper model '%s' ...", self.model_size)
        start = time.monotonic()

        with self._model_lock:
            self._model = WhisperModel(
                self.model_size,
                device=self.device,
                compute_type=self.compute_type,
            )

        elapsed = time.monotonic() - start
        logger.info("Model loaded in %.1f s", elapsed)
        self.on_status_change("ready")

    def start(self) -> None:
        """Start the transcription worker thread."""
        if self._model is None:
            raise RuntimeError("Call load_model() before start()")

        self._running = True
        self._thread = threading.Thread(
            target=self._worker_loop,
            name="TranscriptionWorker",
            daemon=True,
        )
        self._thread.start()
        logger.info("Transcription worker started")

    def stop(self) -> None:
        """Signal the worker to stop and wait for it to finish."""
        self._running = False
        # Unblock the queue.get() call with a sentinel
        self.speech_queue.put(None)
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
        logger.info("Transcription worker stopped")

    @property
    def is_ready(self) -> bool:
        return self._model is not None

    @property
    def model_info(self) -> str:
        return f"{self.model_size} | {self.device} | {self.compute_type}"

    # ------------------------------------------------------------------
    # Internal worker
    # ------------------------------------------------------------------

    def _worker_loop(self) -> None:
        """Continuously pull segments from the queue and transcribe them."""
        while self._running:
            try:
                audio: np.ndarray | None = self.speech_queue.get(timeout=1.0)
            except queue.Empty:
                continue

            if audio is None:
                break  # sentinel received

            self._transcribe(audio)

    def _transcribe(self, audio: np.ndarray) -> None:
        """Run faster-whisper on a single audio segment."""
        self.on_status_change("transcribing")
        start = time.monotonic()

        try:
            with self._model_lock:
                segments, info = self._model.transcribe(
                    audio,
                    language=self.language,
                    beam_size=5,
                    vad_filter=True,           # built-in VAD as second pass
                    vad_parameters={
                        "min_silence_duration_ms": 300,
                        "speech_pad_ms": 100,
                    },
                    word_timestamps=False,
                    condition_on_previous_text=True,
                    temperature=0.0,           # greedy; faster and more consistent
                    no_speech_threshold=0.6,
                    log_prob_threshold=-1.0,
                    compression_ratio_threshold=2.4,
                )

            text_parts = [seg.text for seg in segments]
            text = " ".join(text_parts).strip()

            elapsed = time.monotonic() - start

            if text:
                logger.info(
                    "Transcribed in %.2f s [lang=%s, prob=%.2f]: %s",
                    elapsed, info.language, info.language_probability, text,
                )
                self.on_result(text)
            else:
                logger.debug("Empty transcription result (%.2f s)", elapsed)

        except Exception as exc:
            logger.error("Transcription error: %s", exc, exc_info=True)
        finally:
            self.on_status_change("listening")
```

---

### 4. `typer.py`
Leverages clipboard buffers and PyAutoGUI keyboard simulations in a non-blocking queue.
*   **File Path**: [typer.py](file:///C:/Users/Siddharth/Desktop/Voice-text/voiceflow_local/typer.py)

```python
"""
typer.py - Types transcribed text into the currently active window

Handles:
- Injecting text via pyautogui
- Optional trailing space after each utterance
- Clipboard-based fallback for non-ASCII or long text
- Thread-safe queued typing
"""

import threading
import queue
import logging
import time

logger = logging.getLogger(__name__)

# Delay between typing operations (seconds)
TYPE_DELAY = 0.05

# Characters that need special pyautogui handling on Windows
_PYAUTOGUI_SAFE = True


def _ensure_pyautogui() -> bool:
    """Verify pyautogui is importable and functional."""
    global _PYAUTOGUI_SAFE
    try:
        import pyautogui
        pyautogui.FAILSAFE = False   # disable corner-of-screen fail-safe
        pyautogui.PAUSE = 0.0        # no inter-call pause (we manage timing)
        _PYAUTOGUI_SAFE = True
        return True
    except Exception as exc:
        logger.error("pyautogui unavailable: %s", exc)
        _PYAUTOGUI_SAFE = False
        return False


class TextTyper:
    """
    Receives transcribed text and types it into the currently focused window.

    Typing happens asynchronously in a dedicated thread so that audio capture
    and transcription are never blocked by UI focus delays.
    """

    def __init__(self, append_space: bool = True, use_clipboard: bool = True):
        """
        Args:
            append_space:  Append a space after each typed utterance.
            use_clipboard: Use clipboard paste for speed (recommended on Windows).
        """
        self.append_space = append_space
        self.use_clipboard = use_clipboard

        self._queue: queue.Queue = queue.Queue()
        self._running = False
        self._thread: threading.Thread | None = None
        self._available = _ensure_pyautogui()

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
        logger.info("TextTyper stopped")

    def type_text(self, text: str) -> None:
        """Enqueue text for typing. Returns immediately."""
        if not self._available or not text:
            return
        if self.append_space:
            text = text + " "
        self._queue.put(text)
        logger.debug("Queued for typing: %r", text[:60])

    @property
    def is_available(self) -> bool:
        return self._available

    # ------------------------------------------------------------------
    # Internal worker
    # ------------------------------------------------------------------

    def _worker_loop(self) -> None:
        while self._running:
            try:
                text: str | None = self._queue.get(timeout=1.0)
            except queue.Empty:
                continue

            if text is None:
                break  # sentinel

            self._do_type(text)

    def _do_type(self, text: str) -> None:
        """Perform the actual keystroke injection."""
        # Small delay to ensure the previously active window regains focus
        # after the user interacted with our overlay window.
        time.sleep(TYPE_DELAY)

        try:
            if self.use_clipboard:
                self._type_via_clipboard(text)
            else:
                self._type_via_pyautogui(text)
        except Exception as exc:
            logger.error("Typing error: %s", exc, exc_info=True)

    def _type_via_clipboard(self, text: str) -> None:
        """
        Copy text to clipboard, paste with Ctrl+V, then restore original clipboard.
        This is the most reliable method on Windows for Unicode text.
        """
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
        """
        Type character by character using pyautogui.typewrite.
        Slower but does not touch the clipboard.
        """
        import pyautogui
        # typewrite only supports ASCII; use write() for full Unicode
        pyautogui.write(text, interval=0.01)


def _check_pyperclip() -> bool:
    """Check if pyperclip is available (needed for clipboard typing)."""
    try:
        import pyperclip
        return True
    except ImportError:
        return False


# Auto-detect best typing method at module load time
_HAS_PYPERCLIP = _check_pyperclip()

if not _HAS_PYPERCLIP:
    logger.info(
        "pyperclip not found — clipboard typing unavailable. "
        "Install with: pip install pyperclip"
    )
```

---

### 5. `ui.py`
Tkinter-based floating window using immersive Windows dark theme attributes and canvas-drawn widgets.
*   **File Path**: [ui.py](file:///C:/Users/Siddharth/Desktop/Voice-text/voiceflow_local/ui.py)

```python
"""
ui.py - Main application window for VoiceFlow Local

Dark, minimal, floating overlay-style UI built with tkinter.
All UI mutations happen on the main thread via after() scheduling.
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import threading
import logging
import queue
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# Design tokens
# ------------------------------------------------------------------
COLORS = {
    "bg":           "#0f0f11",
    "surface":      "#1a1a1f",
    "surface2":     "#242429",
    "border":       "#2e2e36",
    "accent":       "#7c6af7",
    "accent_dim":   "#4f46a0",
    "accent_hover": "#9d8fff",
    "green":        "#22c55e",
    "red":          "#ef4444",
    "orange":       "#f97316",
    "text":         "#e8e8f0",
    "text_muted":   "#8888a0",
    "text_dim":     "#555568",
    "scrollbar":    "#2e2e36",
}

FONTS = {
    "title":  ("Segoe UI", 13, "bold"),
    "body":   ("Segoe UI", 10),
    "small":  ("Segoe UI", 9),
    "mono":   ("Consolas", 10),
    "status": ("Segoe UI", 9, "bold"),
    "hotkey": ("Segoe UI", 8),
}

STATUS_CONFIG = {
    "idle":             {"label": "⬤  Idle",          "color": COLORS["text_dim"]},
    "loading":          {"label": "⬤  Loading model…", "color": COLORS["orange"]},
    "ready":            {"label": "⬤  Ready",          "color": COLORS["green"]},
    "listening":        {"label": "⬤  Listening",      "color": COLORS["accent"]},
    "listening_active": {"label": "◉  Speaking…",      "color": COLORS["green"]},
    "transcribing":     {"label": "⬤  Transcribing…",  "color": COLORS["orange"]},
    "error":            {"label": "⬤  Error",          "color": COLORS["red"]},
}


# ------------------------------------------------------------------
# Reusable styled button
# ------------------------------------------------------------------

class StyledButton(tk.Canvas):
    """
    A canvas-based button with rounded corners, hover effects, and
    smooth color transitions — all without PIL/Pillow dependency.
    """

    def __init__(
        self,
        parent,
        text: str,
        command,
        width: int = 80,
        height: int = 32,
        bg_color: str = COLORS["accent"],
        bg_hover: str = COLORS["accent_hover"],
        fg_color: str = "#ffffff",
        radius: int = 8,
        font=FONTS["body"],
        **kwargs,
    ):
        super().__init__(
            parent,
            width=width,
            height=height,
            bg=COLORS["bg"],
            highlightthickness=0,
            cursor="hand2",
            **kwargs,
        )
        self._bg = bg_color
        self._bg_hover = bg_hover
        self._fg = fg_color
        self._radius = radius
        self._text = text
        self._font = font
        self._command = command
        self._current_bg = bg_color
        self._disabled = False

        self._draw()
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)

    def _draw(self, bg: str | None = None) -> None:
        color = bg or self._current_bg
        self.delete("all")
        w = int(self["width"])
        h = int(self["height"])
        r = self._radius
        self._round_rect(0, 0, w, h, r, fill=color, outline="")
        self.create_text(
            w // 2, h // 2,
            text=self._text,
            fill=self._fg,
            font=self._font,
            anchor="center",
        )

    def _round_rect(self, x1, y1, x2, y2, r, **kwargs):
        pts = [
            x1 + r, y1,
            x2 - r, y1,
            x2, y1,
            x2, y1 + r,
            x2, y2 - r,
            x2, y2,
            x2 - r, y2,
            x1 + r, y2,
            x1, y2,
            x1, y2 - r,
            x1, y1 + r,
            x1, y1,
        ]
        return self.create_polygon(pts, smooth=True, **kwargs)

    def _on_enter(self, _event=None):
        if not self._disabled:
            self._current_bg = self._bg_hover
            self._draw()

    def _on_leave(self, _event=None):
        if not self._disabled:
            self._current_bg = self._bg
            self._draw()

    def _on_press(self, _event=None):
        if not self._disabled:
            self._draw(bg=COLORS["accent_dim"])

    def _on_release(self, _event=None):
        if not self._disabled:
            self._on_enter()
            self._command()

    def configure_state(self, disabled: bool) -> None:
        self._disabled = disabled
        if disabled:
            self._current_bg = COLORS["border"]
            self._fg = COLORS["text_dim"]
        else:
            self._current_bg = self._bg
            self._fg = "#ffffff"
        self._draw()

    def set_text(self, text: str) -> None:
        self._text = text
        self._draw()


# ------------------------------------------------------------------
# Audio level meter
# ------------------------------------------------------------------

class LevelMeter(tk.Canvas):
    """Horizontal bar showing real-time microphone input level."""

    def __init__(self, parent, width: int = 200, height: int = 6, **kwargs):
        super().__init__(
            parent,
            width=width,
            height=height,
            bg=COLORS["surface2"],
            highlightthickness=0,
            **kwargs,
        )
        self._width = width
        self._height = height
        self._level = 0.0
        self._bar_id = None
        self._draw(0.0)

    def set_level(self, level: float) -> None:
        """Update the bar fill (0.0–1.0). Must be called from main thread."""
        level = max(0.0, min(1.0, level))
        if abs(level - self._level) > 0.01:
            self._level = level
            self._draw(level)

    def _draw(self, level: float) -> None:
        self.delete("all")
        # Background track
        self._round_rect(0, 0, self._width, self._height, 3,
                         fill=COLORS["border"], outline="")
        # Active fill
        fill_w = int(self._width * level)
        if fill_w > 4:
            color = COLORS["green"] if level < 0.7 else COLORS["orange"]
            self._round_rect(0, 0, fill_w, self._height, 3,
                             fill=color, outline="")

    def _round_rect(self, x1, y1, x2, y2, r, **kwargs):
        pts = [
            x1 + r, y1,
            x2 - r, y1,
            x2, y1,
            x2, y1 + r,
            x2, y2 - r,
            x2, y2,
            x2 - r, y2,
            x1 + r, y2,
            x1, y2,
            x1, y2 - r,
            x1, y1 + r,
            x1, y1,
        ]
        return self.create_polygon(pts, smooth=True, **kwargs)


# ------------------------------------------------------------------
# Main application window
# ------------------------------------------------------------------

class VoiceFlowUI:
    """
    The main application window.

    This class owns the tkinter root and manages all UI state.
    It receives events from background threads via a thread-safe queue
    processed in the main loop using after().
    """

    WINDOW_TITLE = "VoiceFlow Local"
    WINDOW_GEOMETRY = "440x580"
    UPDATE_INTERVAL_MS = 50   # UI refresh rate

    def __init__(self, app_controller):
        """
        Args:
            app_controller: The VoiceFlowApp instance that owns audio/transcription.
        """
        self.ctrl = app_controller
        self._ui_queue: queue.Queue = queue.Queue()
        self._transcript_lines: list[str] = []
        self._is_listening = False
        self._build_window()
        self._start_ui_loop()

    # ------------------------------------------------------------------
    # Window construction
    # ------------------------------------------------------------------

    def _build_window(self) -> None:
        self.root = tk.Tk()
        self.root.title(self.WINDOW_TITLE)
        self.root.geometry(self.WINDOW_GEOMETRY)
        self.root.resizable(True, True)
        self.root.minsize(380, 480)
        self.root.configure(bg=COLORS["bg"])
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # Keep window always on top (floating overlay behavior)
        self.root.attributes("-topmost", True)

        self._apply_dark_title_bar()
        self._build_header()
        self._build_status_bar()
        self._build_level_meter()
        self._build_transcript_area()
        self._build_controls()
        self._build_footer()

    def _apply_dark_title_bar(self) -> None:
        """Use Windows DWM API to darken the title bar on Windows 11."""
        try:
            import ctypes
            DWMWA_USE_IMMERSIVE_DARK_MODE = 20
            hwnd = self.root.winfo_id()
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE,
                ctypes.byref(ctypes.c_int(1)), ctypes.sizeof(ctypes.c_int)
            )
        except Exception:
            pass  # Not on Windows or DWM not available

    def _build_header(self) -> None:
        header = tk.Frame(self.root, bg=COLORS["bg"], padx=16, pady=12)
        header.pack(fill="x")

        left = tk.Frame(header, bg=COLORS["bg"])
        left.pack(side="left")

        # App icon placeholder (Unicode symbol)
        icon = tk.Label(
            left, text="🎙", font=("Segoe UI Emoji", 20),
            bg=COLORS["bg"], fg=COLORS["accent"],
        )
        icon.pack(side="left", padx=(0, 8))

        title_frame = tk.Frame(left, bg=COLORS["bg"])
        title_frame.pack(side="left")

        tk.Label(
            title_frame, text="VoiceFlow Local",
            font=FONTS["title"], bg=COLORS["bg"], fg=COLORS["text"],
        ).pack(anchor="w")

        self._model_label = tk.Label(
            title_frame, text="Loading model…",
            font=FONTS["small"], bg=COLORS["bg"], fg=COLORS["text_muted"],
        )
        self._model_label.pack(anchor="w")

        # Topmost toggle button
        self._topmost = tk.BooleanVar(value=True)
        pin_btn = tk.Checkbutton(
            header,
            text="📌",
            variable=self._topmost,
            command=self._toggle_topmost,
            bg=COLORS["bg"],
            fg=COLORS["text_muted"],
            activebackground=COLORS["bg"],
            activeforeground=COLORS["accent"],
            selectcolor=COLORS["bg"],
            relief="flat",
            cursor="hand2",
            font=("Segoe UI Emoji", 13),
            bd=0,
        )
        pin_btn.pack(side="right")

    def _build_status_bar(self) -> None:
        bar = tk.Frame(
            self.root, bg=COLORS["surface"],
            padx=16, pady=8,
        )
        bar.pack(fill="x", padx=12, pady=(0, 8))

        self._status_var = tk.StringVar(value="⬤  Idle")
        self._status_label = tk.Label(
            bar, textvariable=self._status_var,
            font=FONTS["status"], bg=COLORS["surface"],
            fg=COLORS["text_dim"],
        )
        self._status_label.pack(side="left")

        self._hotkey_label = tk.Label(
            bar, text="F9 to toggle",
            font=FONTS["hotkey"], bg=COLORS["surface"],
            fg=COLORS["text_dim"],
        )
        self._hotkey_label.pack(side="right")

    def _build_level_meter(self) -> None:
        meter_frame = tk.Frame(self.root, bg=COLORS["bg"], padx=12)
        meter_frame.pack(fill="x", pady=(0, 4))

        tk.Label(
            meter_frame, text="MIC",
            font=FONTS["hotkey"], bg=COLORS["bg"], fg=COLORS["text_dim"],
        ).pack(side="left", padx=(0, 6))

        self._level_meter = LevelMeter(meter_frame, height=6)
        self._level_meter.pack(side="left", fill="x", expand=True)

    def _build_transcript_area(self) -> None:
        area_frame = tk.Frame(self.root, bg=COLORS["bg"], padx=12)
        area_frame.pack(fill="both", expand=True, pady=(8, 0))

        tk.Label(
            area_frame, text="TRANSCRIPT",
            font=FONTS["hotkey"], bg=COLORS["bg"], fg=COLORS["text_dim"],
        ).pack(anchor="w", pady=(0, 4))

        text_frame = tk.Frame(area_frame, bg=COLORS["surface"], bd=0)
        text_frame.pack(fill="both", expand=True)

        # Rounded-border illusion using a container frame
        border_frame = tk.Frame(
            area_frame, bg=COLORS["border"], padx=1, pady=1,
        )
        border_frame.pack(fill="both", expand=True)

        inner = tk.Frame(border_frame, bg=COLORS["surface"])
        inner.pack(fill="both", expand=True)

        self._transcript_text = tk.Text(
            inner,
            wrap="word",
            bg=COLORS["surface"],
            fg=COLORS["text"],
            font=FONTS["mono"],
            relief="flat",
            padx=10,
            pady=10,
            insertbackground=COLORS["accent"],
            selectbackground=COLORS["accent_dim"],
            selectforeground=COLORS["text"],
            cursor="arrow",
        )
        self._transcript_text.pack(side="left", fill="both", expand=True)
        self._transcript_text.config(state="disabled")

        scrollbar = tk.Scrollbar(
            inner, command=self._transcript_text.yview,
            bg=COLORS["surface"], troughcolor=COLORS["surface"],
            activebackground=COLORS["border"], relief="flat", width=6,
        )
        scrollbar.pack(side="right", fill="y")
        self._transcript_text.config(yscrollcommand=scrollbar.set)

    def _build_controls(self) -> None:
        ctrl_frame = tk.Frame(self.root, bg=COLORS["bg"], padx=12, pady=10)
        ctrl_frame.pack(fill="x")

        # Row 1: Start / Stop
        row1 = tk.Frame(ctrl_frame, bg=COLORS["bg"])
        row1.pack(fill="x", pady=(0, 6))

        self._start_btn = StyledButton(
            row1, "▶  Start",
            command=self._on_start_clicked,
            width=180, height=36,
            bg_color=COLORS["accent"],
            bg_hover=COLORS["accent_hover"],
        )
        self._start_btn.pack(side="left", padx=(0, 6))

        self._stop_btn = StyledButton(
            row1, "■  Stop",
            command=self._on_stop_clicked,
            width=180, height=36,
            bg_color="#3a1a1a",
            bg_hover=COLORS["red"],
        )
        self._stop_btn.pack(side="left")

        # Row 2: Copy / Save / Clear + sensitivity slider
        row2 = tk.Frame(ctrl_frame, bg=COLORS["bg"])
        row2.pack(fill="x", pady=(4, 0))

        self._copy_btn = StyledButton(
            row2, "⎘ Copy",
            command=self._on_copy_clicked,
            width=112, height=30,
            bg_color=COLORS["surface2"],
            bg_hover=COLORS["surface"],
            font=FONTS["small"],
        )
        self._copy_btn.pack(side="left", padx=(0, 4))

        self._save_btn = StyledButton(
            row2, "💾 Save",
            command=self._on_save_clicked,
            width=112, height=30,
            bg_color=COLORS["surface2"],
            bg_hover=COLORS["surface"],
            font=FONTS["small"],
        )
        self._save_btn.pack(side="left", padx=(0, 4))

        self._clear_btn = StyledButton(
            row2, "🗑 Clear",
            command=self._on_clear_clicked,
            width=112, height=30,
            bg_color=COLORS["surface2"],
            bg_hover="#3a1a1a",
            font=FONTS["small"],
        )
        self._clear_btn.pack(side="left")

        # Sensitivity slider
        sens_frame = tk.Frame(ctrl_frame, bg=COLORS["bg"])
        sens_frame.pack(fill="x", pady=(8, 0))

        tk.Label(
            sens_frame, text="VAD Sensitivity",
            font=FONTS["small"], bg=COLORS["bg"], fg=COLORS["text_muted"],
        ).pack(side="left")

        self._sensitivity_var = tk.IntVar(value=2)
        slider = ttk.Scale(
            sens_frame,
            from_=0, to=3,
            orient="horizontal",
            variable=self._sensitivity_var,
            command=self._on_sensitivity_changed,
        )
        slider.pack(side="left", fill="x", expand=True, padx=8)

        self._sens_value_label = tk.Label(
            sens_frame, text="2",
            font=FONTS["small"], bg=COLORS["bg"], fg=COLORS["text_muted"],
            width=2,
        )
        self._sens_value_label.pack(side="left")

        # Style the slider
        style = ttk.Style()
        style.theme_use("clam")
        style.configure(
            "TScale",
            background=COLORS["bg"],
            troughcolor=COLORS["surface2"],
            slidercolor=COLORS["accent"],
        )

    def _build_footer(self) -> None:
        footer = tk.Frame(self.root, bg=COLORS["bg"], padx=12, pady=6)
        footer.pack(fill="x")

        self._word_count_label = tk.Label(
            footer, text="0 words",
            font=FONTS["hotkey"], bg=COLORS["bg"], fg=COLORS["text_dim"],
        )
        self._word_count_label.pack(side="left")

        tk.Label(
            footer, text="100% offline · no APIs",
            font=FONTS["hotkey"], bg=COLORS["bg"], fg=COLORS["text_dim"],
        ).pack(side="right")

    # ------------------------------------------------------------------
    # UI event loop & thread-safe updates
    # ------------------------------------------------------------------

    def _start_ui_loop(self) -> None:
        self.root.after(self.UPDATE_INTERVAL_MS, self._ui_loop)

    def _ui_loop(self) -> None:
        """Drain the thread-safe queue and update the UI on the main thread."""
        try:
            while True:
                cmd, *args = self._ui_queue.get_nowait()
                handler = getattr(self, f"_handle_{cmd}", None)
                if handler:
                    handler(*args)
        except queue.Empty:
            pass

        # Update audio level meter
        if self._is_listening and self.ctrl.audio_handler:
            self._level_meter.set_level(self.ctrl.audio_handler.audio_level)
        else:
            self._level_meter.set_level(0.0)

        self.root.after(self.UPDATE_INTERVAL_MS, self._ui_loop)

    def schedule(self, command: str, *args) -> None:
        """Thread-safe: enqueue a UI update from any thread."""
        self._ui_queue.put((command, *args))

    # Handlers dispatched from the queue:

    def _handle_set_status(self, status: str) -> None:
        cfg = STATUS_CONFIG.get(status, STATUS_CONFIG["idle"])
        self._status_var.set(cfg["label"])
        self._status_label.config(fg=cfg["color"])

    def _handle_append_transcript(self, text: str) -> None:
        self._transcript_lines.append(text)
        self._transcript_text.config(state="normal")
        if self._transcript_text.index("end-1c") != "1.0":
            self._transcript_text.insert("end", "\n")
        self._transcript_text.insert("end", text)
        self._transcript_text.see("end")
        self._transcript_text.config(state="disabled")
        self._update_word_count()

    def _handle_set_model_info(self, info: str) -> None:
        self._model_label.config(text=info)

    def _handle_set_listening(self, listening: bool) -> None:
        self._is_listening = listening
        self._start_btn.configure_state(disabled=listening)
        self._stop_btn.configure_state(disabled=not listening)

    def _handle_show_error(self, message: str) -> None:
        messagebox.showerror("VoiceFlow Error", message, parent=self.root)

    def _handle_show_info(self, message: str) -> None:
        messagebox.showinfo("VoiceFlow", message, parent=self.root)

    # ------------------------------------------------------------------
    # Button callbacks (main thread)
    # ------------------------------------------------------------------

    def _on_start_clicked(self) -> None:
        self.ctrl.start_listening()

    def _on_stop_clicked(self) -> None:
        self.ctrl.stop_listening()

    def _on_copy_clicked(self) -> None:
        text = self._get_transcript_text()
        if text:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            self._copy_btn.set_text("✓ Copied!")
            self.root.after(1500, lambda: self._copy_btn.set_text("⎘ Copy"))
        else:
            self.schedule("show_info", "Transcript is empty.")

    def _on_save_clicked(self) -> None:
        text = self._get_transcript_text()
        if not text:
            self.schedule("show_info", "Transcript is empty.")
            return

        filepath = filedialog.asksaveasfilename(
            parent=self.root,
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
            title="Save Transcript",
            initialfile="voiceflow_transcript.txt",
        )
        if filepath:
            try:
                Path(filepath).write_text(text, encoding="utf-8")
                self.schedule("show_info", f"Saved to:\n{filepath}")
            except Exception as exc:
                self.schedule("show_error", f"Could not save file:\n{exc}")

    def _on_clear_clicked(self) -> None:
        self._transcript_lines.clear()
        self._transcript_text.config(state="normal")
        self._transcript_text.delete("1.0", "end")
        self._transcript_text.config(state="disabled")
        self._update_word_count()

    def _on_sensitivity_changed(self, value: str) -> None:
        val = int(float(value))
        self._sensitivity_var.set(val)
        self._sens_value_label.config(text=str(val))
        self.ctrl.set_sensitivity(val)

    def _toggle_topmost(self) -> None:
        self.root.attributes("-topmost", self._topmost.get())

    def _on_close(self) -> None:
        self.ctrl.shutdown()
        self.root.destroy()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_transcript_text(self) -> str:
        return self._transcript_text.get("1.0", "end-1c").strip()

    def _update_word_count(self) -> None:
        text = self._get_transcript_text()
        words = len(text.split()) if text else 0
        self._word_count_label.config(text=f"{words} word{'s' if words != 1 else ''}")

    # ------------------------------------------------------------------
    # Main event loop
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Start the tkinter main loop (blocking)."""
        self.root.mainloop()
```

---

### 6. `utils.py`
Exposes the global hook keyboard event wrapper and diagnostics log printers.
*   **File Path**: [utils.py](file:///C:/Users/Siddharth/Desktop/Voice-text/voiceflow_local/utils.py)

```python
"""
utils.py - Shared utilities for VoiceFlow Local

Provides:
- Logging setup
- File save helpers
- Hotkey manager wrapper
- System info detection
"""

import logging
import sys
import os
import datetime
import platform
import threading
from pathlib import Path

# ------------------------------------------------------------------
# Logging
# ------------------------------------------------------------------

def setup_logging(level: int = logging.INFO) -> None:
    """Configure root logger to write to console with a clean format."""
    fmt = "%(asctime)s  %(levelname)-8s  %(name)-22s  %(message)s"
    date_fmt = "%H:%M:%S"

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(fmt, date_fmt))

    root = logging.getLogger()
    root.setLevel(level)
    # Avoid duplicate handlers if called more than once
    if not root.handlers:
        root.addHandler(handler)

    # Quieten overly verbose libraries
    logging.getLogger("faster_whisper").setLevel(logging.WARNING)
    logging.getLogger("ctranslate2").setLevel(logging.WARNING)
    logging.getLogger("numba").setLevel(logging.WARNING)


# ------------------------------------------------------------------
# File helpers
# ------------------------------------------------------------------

def save_transcript(text: str, directory: str | None = None) -> Path:
    """
    Save transcript text to a timestamped .txt file.

    Args:
        text:      The transcript content.
        directory: Target directory. Defaults to the user's Desktop.

    Returns:
        Path of the saved file.
    """
    if not directory:
        directory = Path.home() / "Desktop"
    else:
        directory = Path(directory)

    directory.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = directory / f"voiceflow_transcript_{timestamp}.txt"

    filename.write_text(text, encoding="utf-8")
    logging.getLogger(__name__).info("Transcript saved to %s", filename)
    return filename


# ------------------------------------------------------------------
# System info
# ------------------------------------------------------------------

def get_system_info() -> dict:
    """Return a dictionary of useful system diagnostics."""
    info = {
        "platform": platform.platform(),
        "python": sys.version,
        "cpu_count": os.cpu_count(),
    }

    # CUDA check
    try:
        import torch
        info["cuda_available"] = torch.cuda.is_available()
        if torch.cuda.is_available():
            info["cuda_device"] = torch.cuda.get_device_name(0)
            info["cuda_version"] = torch.version.cuda
    except ImportError:
        info["cuda_available"] = False

    # CTranslate2 CUDA check (fallback)
    if not info.get("cuda_available"):
        try:
            import ctranslate2
            count = ctranslate2.get_cuda_device_count()
            info["cuda_available"] = count > 0
            info["cuda_device_count"] = count
        except Exception:
            pass

    return info


def log_system_info() -> None:
    """Print system info to the console."""
    info = get_system_info()
    logger = logging.getLogger(__name__)
    logger.info("=== System Info ===")
    for k, v in info.items():
        logger.info("  %s: %s", k, v)
    logger.info("===================")


# ------------------------------------------------------------------
# Hotkey manager
# ------------------------------------------------------------------

class HotkeyManager:
    """
    Registers and manages global keyboard hotkeys using the `keyboard` library.
    Hotkeys remain active even when the application window is not focused.
    """

    def __init__(self):
        self._hotkeys: dict[str, int] = {}  # hotkey_str -> handler id
        self._lock = threading.Lock()
        self._available = self._check_keyboard()

    @staticmethod
    def _check_keyboard() -> bool:
        try:
            import keyboard  # noqa: F401
            return True
        except ImportError:
            logging.getLogger(__name__).warning(
                "keyboard library not found — hotkeys disabled. "
                "Install with: pip install keyboard"
            )
            return False

    def register(self, hotkey: str, callback) -> bool:
        """
        Register a global hotkey.

        Args:
            hotkey:   Key combination string, e.g. "f9" or "ctrl+shift+s".
            callback: Zero-argument callable to invoke when the hotkey fires.

        Returns:
            True if registration succeeded.
        """
        if not self._available:
            return False

        import keyboard

        with self._lock:
            # Remove existing handler for this hotkey if present
            if hotkey in self._hotkeys:
                self.unregister(hotkey)

            try:
                handler_id = keyboard.add_hotkey(hotkey, callback, suppress=False)
                self._hotkeys[hotkey] = handler_id
                logging.getLogger(__name__).info("Hotkey registered: %s", hotkey)
                return True
            except Exception as exc:
                logging.getLogger(__name__).warning(
                    "Failed to register hotkey '%s': %s", hotkey, exc
                )
                return False

    def unregister(self, hotkey: str) -> None:
        """Remove a previously registered hotkey."""
        if not self._available:
            return

        import keyboard

        with self._lock:
            if hotkey in self._hotkeys:
                try:
                    keyboard.remove_hotkey(self._hotkeys[hotkey])
                except Exception:
                    pass
                del self._hotkeys[hotkey]

    def unregister_all(self) -> None:
        """Remove all registered hotkeys."""
        for hotkey in list(self._hotkeys.keys()):
            self.unregister(hotkey)

    @property
    def is_available(self) -> bool:
        return self._available
```

---

### 7. `requirements.txt`
Package versions mapped specifically for maximum CTranslate2 and sounddevice alignment.
*   **File Path**: [requirements.txt](file:///C:/Users/Siddharth/Desktop/Voice-text/voiceflow_local/requirements.txt)

```text
sounddevice>=0.4.6
numpy>=1.20,<2.0
webrtcvad>=2.0.10
faster-whisper>=0.10.0
pyperclip>=1.8.2
pyautogui>=0.9.54
keyboard>=0.13.5
torch>=2.0.0
```

---

### 8. `setup.bat`
Windows batch installer script designed to construct the virtual environment automatically.
*   **File Path**: [setup.bat](file:///C:/Users/Siddharth/Desktop/Voice-text/voiceflow_local/setup.bat)

```bat
@echo off
title VoiceFlow Local Auto-Installer
echo ===================================================
echo      VoiceFlow Local - Automated Setup Utility
echo ===================================================
echo.

:: Verify Python Installation
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python is not installed or not added to your system PATH.
    echo Please install Python 3.10+ and select "Add to PATH" before continuing.
    pause
    exit /b 1
)

:: Create Virtual Environment
echo [1/4] Creating a clean virtual environment (.venv) ...
python -m venv .venv
if %errorlevel% neq 0 (
    echo [ERROR] Failed to construct virtual environment.
    pause
    exit /b 1
)

:: Activate Virtual Environment
echo [2/4] Activating virtual environment ...
call .venv\Scripts\activate.bat

:: Upgrade pip
echo [3/4] Upgrading package manager (pip) ...
python -m pip install --upgrade pip

:: Install dependencies
echo [4/4] Installing offline dependencies from requirements.txt ...
pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo.
    echo [WARNING] Dependency installation encountered warning flags.
    echo Proceeding to install pyperclip fallback explicitly...
    pip install pyperclip
)

echo.
echo ===================================================
echo   [SUCCESS] Setup Completed!
echo ===================================================
echo.
echo   To launch the application:
echo     1. Ensure virtual env is active:  .venv\Scripts\activate
echo     2. Run the program:             python main.py
echo.
pause
```
