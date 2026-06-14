"""
wake_word.py - "Hello Echo" wake word detection for NirmiqEcho

Architecture:
  - Runs a lightweight always-on background audio stream (tiny Whisper model)
  - Collects 2.5-second rolling chunks from the mic
  - Transcribes each chunk with faster-whisper tiny (fast, ~100ms per chunk on CPU)
  - Checks for the wake phrase "hello echo" (+ common variations)
  - Fires on_wake callback on detection → NirmiqEchoApp activates main listening

CPU usage: ~3-5% idle (tiny model, int8, 2.5s polling window)
Memory: ~80MB for tiny model

The detector uses a SEPARATE audio stream from AudioHandler so both can
coexist cleanly. When main listening is active, the wake detector pauses
itself to avoid double-recording.
"""

import threading
import queue
import logging
import time
import re
import numpy as np

logger = logging.getLogger(__name__)

# Wake word configuration
WAKE_PHRASES = {
    "hello echo",
    "hey echo",
    "hi echo",
    "hello, echo",
    "hey, echo",
    "ok echo",
    "okay echo",
}

# Audio settings (must match VAD requirements)
SAMPLE_RATE = 16000
CHUNK_SECONDS = 2.5          # length of each chunk fed to tiny Whisper
CHUNK_SAMPLES = int(SAMPLE_RATE * CHUNK_SECONDS)
OVERLAP_RATIO = 0.4          # 40% overlap so we don't miss cross-boundary phrases
OVERLAP_SAMPLES = int(CHUNK_SAMPLES * OVERLAP_RATIO)

# Detection confidence threshold
MIN_LANG_PROB = 0.50         # accept if Whisper thinks it's ≥50% sure of the language


class WakeWordDetector:
    """
    Continuously listens for "Hello Echo" using Whisper tiny model.

    Lifecycle:
        1. load_model() — load tiny Whisper (call in background thread)
        2. start()      — begin mic capture + detection loop
        3. pause()      — suspend detection while main transcription is active
        4. resume()     — re-enable detection when main transcription finishes
        5. stop()       — shut down permanently
    """

    def __init__(self, on_wake, on_status_change=None):
        """
        Args:
            on_wake: Callable fired when wake word is detected. Called from
                     the detection thread — must be thread-safe.
            on_status_change: Optional Callable(status: str) for UI updates.
        """
        self.on_wake = on_wake
        self.on_status_change = on_status_change or (lambda s: None)

        self._model = None
        self._model_lock = threading.Lock()

        self._stream = None
        self._running = False
        self._paused = False     # True while main listening is active
        self._lock = threading.Lock()

        # Rolling audio buffer (samples as float32)
        self._buffer: list[np.ndarray] = []
        self._buffer_lock = threading.Lock()
        self._buffer_samples = 0

        self._detect_thread: threading.Thread | None = None
        self._audio_queue: queue.Queue = queue.Queue(maxsize=10)

        # Cooldown: don't fire again within 3 seconds of last activation
        self._last_wake_time = 0.0
        self._cooldown_seconds = 3.0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_model(self) -> None:
        """Load Whisper tiny.en — call once in a background thread."""
        from faster_whisper import WhisperModel
        import os

        logger.info("WakeWordDetector: loading Whisper tiny.en model…")
        start = time.monotonic()

        cache_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", "models"
        )
        os.makedirs(cache_dir, exist_ok=True)

        with self._model_lock:
            try:
                self._model = WhisperModel(
                    "tiny.en",
                    device="cpu",
                    compute_type="int8",
                    local_files_only=True,
                    download_root=cache_dir,
                )
            except Exception:
                # First run — download from HuggingFace
                self._model = WhisperModel(
                    "tiny.en",
                    device="cpu",
                    compute_type="int8",
                    download_root=cache_dir,
                )

        logger.info("WakeWordDetector: tiny.en loaded in %.1fs",
                    time.monotonic() - start)


    def start(self) -> None:
        """Open mic stream and begin wake word detection loop."""
        if self._model is None:
            raise RuntimeError("Call load_model() before start()")

        with self._lock:
            if self._running:
                return
            self._running = True
            self._paused = False

        self._open_stream()
        self._detect_thread = threading.Thread(
            target=self._detection_loop,
            name="WakeWordDetector",
            daemon=True,
        )
        self._detect_thread.start()
        logger.info("WakeWordDetector: started — listening for 'Hello Echo'")
        self.on_status_change("standby")

    def stop(self) -> None:
        """Permanently shut down the detector."""
        with self._lock:
            if not self._running:
                return
            self._running = False

        self._close_stream()
        self._audio_queue.put(None)  # unblock detection loop
        if self._detect_thread:
            self._detect_thread.join(timeout=5)
            self._detect_thread = None
        logger.info("WakeWordDetector: stopped")

    def pause(self) -> None:
        """Suspend detection while main transcription is running."""
        with self._lock:
            self._paused = True
        logger.debug("WakeWordDetector: paused")

    def resume(self) -> None:
        """Resume detection after main transcription ends."""
        with self._lock:
            self._paused = False
        # Clear stale buffer
        with self._buffer_lock:
            self._buffer.clear()
            self._buffer_samples = 0
        logger.debug("WakeWordDetector: resumed")
        self.on_status_change("standby")

    @property
    def is_running(self) -> bool:
        return self._running and not self._paused

    @property
    def is_ready(self) -> bool:
        return self._model is not None

    # ------------------------------------------------------------------
    # Audio stream
    # ------------------------------------------------------------------

    def _open_stream(self) -> None:
        import sounddevice as sd

        def _callback(indata, frames, time_info, status):
            if status:
                logger.debug("WakeWord stream status: %s", status)
            if not self._running or self._paused:
                return
            pcm = np.frombuffer(bytes(indata), dtype=np.int16).astype(np.float32) / 32768.0
            try:
                self._audio_queue.put_nowait(pcm)
            except queue.Full:
                pass  # drop oldest chunk, keep latency low

        try:
            self._stream = sd.RawInputStream(
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype="int16",
                blocksize=int(SAMPLE_RATE * 0.1),   # 100ms callback blocks
                callback=_callback,
            )
            self._stream.start()
            logger.debug("WakeWordDetector: mic stream open")
        except Exception as exc:
            self._running = False
            raise RuntimeError(f"WakeWordDetector could not open mic: {exc}") from exc

    def _close_stream(self) -> None:
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception as exc:
                logger.warning("WakeWordDetector: error closing stream: %s", exc)
            finally:
                self._stream = None

    # ------------------------------------------------------------------
    # Detection loop
    # ------------------------------------------------------------------

    def _detection_loop(self) -> None:
        """Consumer thread: accumulate audio, run Whisper tiny, check phrases."""
        while self._running:
            try:
                chunk = self._audio_queue.get(timeout=0.5)
            except queue.Empty:
                continue

            if chunk is None:
                break

            with self._lock:
                if self._paused:
                    continue

            # Accumulate into rolling buffer
            with self._buffer_lock:
                self._buffer.append(chunk)
                self._buffer_samples += len(chunk)

                # Keep only what we need
                while self._buffer_samples > CHUNK_SAMPLES + OVERLAP_SAMPLES:
                    removed = self._buffer.pop(0)
                    self._buffer_samples -= len(removed)

                if self._buffer_samples < CHUNK_SAMPLES:
                    continue   # not enough audio yet

                audio = np.concatenate(self._buffer)[-CHUNK_SAMPLES:]

            # Check cooldown
            if time.monotonic() - self._last_wake_time < self._cooldown_seconds:
                continue

            # Run detection
            detected = self._detect(audio)
            if detected:
                self._last_wake_time = time.monotonic()
                logger.info("WakeWordDetector: WAKE WORD DETECTED!")
                self.on_status_change("wake_detected")
                # Fire callback (app will call pause() shortly after)
                try:
                    self.on_wake()
                except Exception as exc:
                    logger.error("WakeWordDetector: on_wake callback error: %s", exc)

    def _detect(self, audio: np.ndarray) -> bool:
        """Run Whisper tiny on the chunk and check for wake phrase."""
        try:
            with self._model_lock:
                segments, info = self._model.transcribe(
                    audio,
                    language="en",      # force English for speed
                    beam_size=1,        # fastest mode for wake word
                    best_of=1,
                    temperature=0.0,
                    no_speech_threshold=0.7,   # high threshold — only clear speech
                    vad_filter=True,
                    condition_on_previous_text=False,
                    word_timestamps=False,
                )

            if info.language_probability < MIN_LANG_PROB:
                return False

            text = " ".join(s.text for s in segments).lower().strip()
            if not text:
                return False

            # Remove punctuation for matching
            normalized = re.sub(r"[^\w\s]", "", text)

            for phrase in WAKE_PHRASES:
                if phrase in normalized:
                    logger.debug("WakeWord match: '%s' in '%s'", phrase, normalized)
                    return True

            return False

        except Exception as exc:
            logger.debug("WakeWordDetector: detection error (non-fatal): %s", exc)
            return False
