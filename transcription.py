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


def _detect_compute_device():
    """
    Detect whether CUDA is available.
    Returns ("cuda", "float16") if GPU found, ("cpu", "int8") otherwise.
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
    return "large-v3" if device == "cuda" else "medium"


class TranscriptionEngine:
    """
    Pulls audio segments from a queue, transcribes them with faster-whisper,
    and dispatches text results via callback. Runs in its own daemon thread.
    """

    def __init__(
        self,
        speech_queue: queue.Queue,
        on_result,
        on_status_change=None,
        model_size=None,
        language=None,
    ):
        self.speech_queue = speech_queue
        self.on_result = on_result
        self.on_status_change = on_status_change or (lambda s: None)
        self.language = language

        self._running = False
        self._thread = None
        self._model = None
        self._model_lock = threading.Lock()

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
        """Load the faster-whisper model (call in a background thread)."""
        from faster_whisper import WhisperModel

        logger.info("Loading faster-whisper model '%s' ...", self.model_size)
        start = time.monotonic()

        with self._model_lock:
            # Try local cache first for near-instant load; fall back to download
            try:
                self._model = WhisperModel(
                    self.model_size,
                    device=self.device,
                    compute_type=self.compute_type,
                    local_files_only=True,
                )
                logger.info("Loaded from local cache")
            except Exception:
                logger.info("Cache miss — downloading model '%s'", self.model_size)
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
        self.speech_queue.put(None)  # sentinel to unblock queue.get()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
        logger.info("Transcription worker stopped")

    @property
    def is_ready(self) -> bool:
        return self._model is not None

    @property
    def model_info(self) -> str:
        return f"{self.model_size}  ·  {self.device}  ·  {self.compute_type}"

    # ------------------------------------------------------------------
    # Internal worker
    # ------------------------------------------------------------------

    def _worker_loop(self) -> None:
        """Continuously pull segments from the queue and transcribe them."""
        while self._running:
            try:
                audio = self.speech_queue.get(timeout=1.0)
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
                    vad_filter=True,
                    vad_parameters={
                        "min_silence_duration_ms": 300,
                        "speech_pad_ms": 100,
                    },
                    word_timestamps=False,
                    condition_on_previous_text=True,
                    temperature=0.0,
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
