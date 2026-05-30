"""
audio_handler.py - Microphone capture and Voice Activity Detection (VAD)

Handles:
- Microphone stream using sounddevice
- Real-time VAD using webrtcvad (or webrtcvad-wheels — same API)
- Silence detection and speech segment extraction
- Thread-safe audio buffer management
"""

import threading
import queue
import logging
import numpy as np
import sounddevice as sd

try:
    import webrtcvad
except ImportError:
    raise ImportError(
        "webrtcvad not found. Install with:\n"
        "  pip install webrtcvad-wheels"
    )

logger = logging.getLogger(__name__)

# VAD requires audio at specific sample rates
VAD_SAMPLE_RATE = 16000  # 16 kHz required by webrtcvad

# webrtcvad processes frames of 10ms, 20ms, or 30ms
FRAME_DURATION_MS = 30  # 30ms frames
FRAME_SIZE = int(VAD_SAMPLE_RATE * FRAME_DURATION_MS / 1000)  # 480 samples per frame

# Silence detection settings
SILENCE_THRESHOLD_FRAMES = 20   # 600ms of silence before flushing utterance
SPEECH_THRESHOLD_FRAMES = 3     # 90ms of voiced frames to confirm speech started
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
            on_status_change: Callback(status: str) called on detection state changes.
        """
        self.sensitivity = max(0, min(3, sensitivity))
        self.on_status_change = on_status_change or (lambda s: None)

        self._vad = webrtcvad.Vad(self.sensitivity)
        self._stream = None
        self._running = False
        self._lock = threading.Lock()

        # Queue that holds complete speech segments (as numpy float32 arrays)
        self.speech_queue = queue.Queue()

        # Internal buffers
        self._voiced_frames = []

        # State machine counters
        self._num_voiced = 0
        self._num_silent = 0
        self._in_speech = False

        # Audio level for UI feedback (0.0 - 1.0)
        self.audio_level = 0.0

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

    def _audio_callback(self, indata, frames, time_info, status) -> None:
        """
        sounddevice callback — called on a dedicated audio thread.
        Must not block or raise exceptions.
        """
        if status:
            logger.debug("Audio stream status: %s", status)

        if not self._running:
            return

        raw_bytes = bytes(indata)

        # Compute audio level for VU meter
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
                # Buffer brief silences as padding
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
    # Microphone enumeration utilities
    # ------------------------------------------------------------------

    @staticmethod
    def list_input_devices() -> list:
        """Return a list of available input audio devices."""
        devices = []
        for i, dev in enumerate(sd.query_devices()):
            if dev["max_input_channels"] > 0:
                devices.append({"index": i, "name": dev["name"]})
        return devices

    @staticmethod
    def get_default_input_device():
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
