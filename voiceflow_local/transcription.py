"""
transcription.py - Local offline speech-to-text using faster-whisper

Handles:
- Model loading (CPU int8 — medium model, optimised for local use)
- Consuming audio segments from the speech queue
- Running transcription in a background thread
- Dispatching results via callback

Model: whisper-medium  (~1.5 GB RAM, int8 quantised)
  - WhisperFlow-level accuracy for Indian English
  - ~1-2s per utterance on CPU, ~0.3s with GPU
  - Best balance of accuracy / memory / speed for local offline use

Accuracy settings vs baseline:
  - initial_prompt from accent profile (personalises decoder)
  - beam_size 5 → 8   (better accuracy on ambiguous words)
  - best_of   1 → 5   (multiple decoding runs, pick best)
  - language forced to "en" (skip auto-detect, saves ~150ms)
  - no_speech_threshold 0.6 → 0.4 (catches quieter speech)
  - hallucination_silence_threshold (rejects silence hallucinations)
  - condition_on_previous_text=False (avoids cross-segment drift)
"""

import os
import threading
import queue
import logging
import time
import numpy as np

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────
# Hardware detection
# ──────────────────────────────────────────────────────────────────

def _detect_compute_device():
    """
    Detect CUDA availability.
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

    logger.info("No CUDA GPU — using CPU with int8 quantization")
    return "cpu", "int8"


# ------------------------------------------------------------------
# TranscriptionEngine
# ------------------------------------------------------------------

class TranscriptionEngine:
    """
    Pulls audio segments from a queue, transcribes them with faster-whisper,
    and dispatches text results via callback. Runs in its own daemon thread.

    Accuracy improvements over baseline:
      - beam_size=8, best_of=5
      - initial_prompt from AccentProfiler
      - Forced language="en"
      - Lower no_speech_threshold (0.4)
      - hallucination_silence_threshold filter
    """

    def __init__(
        self,
        speech_queue: queue.Queue,
        on_result,
        on_status_change=None,
        model_size: str | None = None,
        language: str | None = "en",
        initial_prompt: str | None = None,
    ):
        """
        Args:
            speech_queue:    Queue[np.ndarray] shared with AudioHandler.
            on_result:       Callback(text: str) called for each transcription.
            on_status_change: Callback(status: str) for UI state updates.
            model_size:      Override model (e.g. "small", "medium", "large-v3").
            language:        Force language code. None = auto-detect per segment.
            initial_prompt:  Accent-tuned context string injected into decoder.
        """
        self.speech_queue = speech_queue
        self.on_result = on_result
        self.on_status_change = on_status_change or (lambda s: None)
        self.language = language
        self.initial_prompt = initial_prompt

        self._running = False
        self._thread: threading.Thread | None = None
        self._model = None
        self._model_lock = threading.Lock()

        self.device, self.compute_type = _detect_compute_device()

        # Model selection — benchmarked 2026-06-10 on the user's real voice
        # samples (see tests/manual/test_accuracy.py):
        #   GPU large-v3 : 99.5% acc, RTF 0.23x (1-2s commands)    ← GPU default
        #   CPU small.en : 97% acc, RTF 0.36x (1-2s commands), 500MB ← CPU default
        #   CPU medium.en: 99% acc, RTF 0.95x (3-5s commands), 1.5GB
        #   CPU large-v3 : 99.5% acc but RTF 1.7-2.8x — not interactive
        #   distil-large-v3: fast but fails Indian accent — do not use
        env_model = os.getenv("WHISPER_MODEL", "").strip()
        if model_size:
            self.model_size = model_size          # explicit override
        elif env_model:
            self.model_size = env_model           # .env override (any device)
        elif self.device == "cuda":
            self.model_size = "large-v3"          # GPU: best model, still fast
        else:
            self.model_size = "small.en"          # CPU: Jarvis-snappy

        logger.info(
            "TranscriptionEngine: model=%s  device=%s  compute=%s  language=%s",
            self.model_size, self.device, self.compute_type,
            self.language or "auto",
        )
        if self.initial_prompt:
            logger.info("TranscriptionEngine: initial_prompt loaded (%d chars)",
                        len(self.initial_prompt))



    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_model(self) -> None:
        """Load the faster-whisper model. Call in a background thread."""
        from faster_whisper import WhisperModel
        import os

        logger.info("Loading faster-whisper '%s' on %s…",
                    self.model_size, self.device)
        start = time.monotonic()

        # Point to a predictable local cache directory (avoids re-downloads)
        cache_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", "models"
        )
        os.makedirs(cache_dir, exist_ok=True)

        # cpu_threads: use all physical cores for faster load + inference
        cpu_threads = min(8, max(2, (os.cpu_count() or 4)))

        # Degradation ladder: each step is (model, device, compute_type).
        # GPU can fail at runtime (missing cuDNN, VRAM taken by a game) —
        # Echo must come up regardless.
        attempts = [(self.model_size, self.device, self.compute_type)]
        if self.device == "cuda":
            attempts.append((self.model_size, "cuda", "int8_float16"))  # half VRAM
            attempts.append(("small.en", "cpu", "int8"))                # CPU rescue
        elif self.model_size != "small.en":
            attempts.append(("small.en", "cpu", "int8"))

        last_exc: Exception | None = None
        with self._model_lock:
            for model_name, device, compute in attempts:
                # Local cache first (instant); then allow download
                for local_only in (True, False):
                    try:
                        self._model = WhisperModel(
                            model_name,
                            device=device,
                            compute_type=compute,
                            local_files_only=local_only,
                            download_root=cache_dir,
                            cpu_threads=cpu_threads,
                            num_workers=2,
                        )
                        self.model_size = model_name
                        self.device = device
                        self.compute_type = compute
                        last_exc = None
                        break
                    except Exception as exc:
                        last_exc = exc
                if self._model is not None:
                    break
                logger.warning("Model %s on %s/%s failed (%s) — trying next rung",
                               model_name, device, compute, last_exc)

        if self._model is None:
            raise RuntimeError(f"All model load attempts failed: {last_exc}")

        elapsed = time.monotonic() - start
        logger.info("Model ready in %.1f s — %s on %s/%s",
                    elapsed, self.model_size, self.device, self.compute_type)
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
        """Signal the worker to stop and wait for it."""
        self._running = False
        self.speech_queue.put(None)   # sentinel to unblock queue.get()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
        logger.info("Transcription worker stopped")

    def update_prompt(self, prompt: str | None) -> None:
        """Update the initial_prompt at runtime (e.g. after accent analysis)."""
        self.initial_prompt = prompt
        logger.info("TranscriptionEngine: initial_prompt updated")

    @property
    def is_ready(self) -> bool:
        return self._model is not None

    @property
    def model_info(self) -> str:
        return f"{self.model_size}  ·  {self.device}  ·  {self.compute_type}"

    # ------------------------------------------------------------------
    # Worker loop
    # ------------------------------------------------------------------

    def _worker_loop(self) -> None:
        """Continuously pull segments from the queue and transcribe them."""
        while self._running:
            try:
                audio = self.speech_queue.get(timeout=1.0)
            except queue.Empty:
                continue

            if audio is None:
                break   # sentinel received

            self._transcribe(audio)

    def _transcribe(self, audio: np.ndarray) -> None:
        """Run faster-whisper on a single audio segment with optimised settings."""
        self.on_status_change("transcribing")
        start = time.monotonic()

        try:
            with self._model_lock:
                segments, info = self._model.transcribe(
                    audio,
                    language=self.language,
                    beam_size=5,    # benchmark: beam 5 == beam 8 quality, ~30% faster
                    best_of=5,      # (ignored at temperature=0 — kept for clarity)
                    initial_prompt=self.initial_prompt, # accent + hotwords primer
                    vad_filter=True,
                    vad_parameters={
                        "min_silence_duration_ms": 300,
                        "speech_pad_ms": 80,
                        "threshold": 0.45,              # higher = ignore background music
                    },
                    word_timestamps=False,
                    condition_on_previous_text=False,   # each segment independent
                    suppress_blank=True,                # skip blank/silence outputs
                    temperature=0.0,                    # greedy, most consistent
                    no_speech_threshold=0.6,            # Whisper default — drop silence but keep quiet speech
                    log_prob_threshold=-0.8,            # reject gibberish outputs
                    compression_ratio_threshold=2.4,
                    hallucination_silence_threshold=2.0,
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
