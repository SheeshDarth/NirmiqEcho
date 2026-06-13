"""faster-whisper transcription with GPU/CPU auto-selection + degradation
ladder. Ported from the proven voiceflow_local engine (RTX 4050: large-v3
float16, ~0.17x RTF, 99.5% on this user's samples; CPU falls back to small.en).
"""
from __future__ import annotations

import os
import threading
import time

import numpy as np

from core.config.settings import get_settings
from core.shared.exceptions import VoiceError
from core.shared.logger import get_logger

log = get_logger(__name__)


def _detect_device() -> tuple[str, str]:
    try:
        import ctranslate2
        if ctranslate2.get_cuda_device_count() > 0:
            return "cuda", "float16"
    except Exception:
        pass
    return "cpu", "int8"


class Transcriber:
    def __init__(self, model_size: str | None = None,
                 initial_prompt: str | None = None):
        self.settings = get_settings()
        self.device, self.compute_type = _detect_device()
        env_model = os.getenv("NIRMIQ_WHISPER_MODEL", "").strip()
        if model_size:
            self.model_size = model_size
        elif env_model:
            self.model_size = env_model
        elif self.device == "cuda":
            self.model_size = "large-v3"
        else:
            self.model_size = self.settings.voice.whisper_model  # small.en
        self.initial_prompt = initial_prompt
        self._model = None
        self._lock = threading.Lock()

    @property
    def is_ready(self) -> bool:
        return self._model is not None

    @property
    def info(self) -> str:
        return f"{self.model_size} · {self.device} · {self.compute_type}"

    def _resolve_cache(self):
        """Reuse an existing whisper cache (config > project models/ > data dir)."""
        from pathlib import Path
        configured = self.settings.voice.model_cache
        if configured and Path(configured).exists():
            return Path(configured)
        # Reuse a sibling models/ cache if present. After consolidation the
        # backend lives under <project>/core, so models/ is two levels up;
        # also probe a couple of likely roots so a rename never breaks it.
        marker = "models--Systran--faster-whisper-large-v3"
        candidates = [
            Path(__file__).resolve().parents[2] / "models",   # <project>/models
            Path.home() / "Desktop" / "NirmiqEcho" / "models",
            Path.home() / "Desktop" / "Voice-text" / "models",
        ]
        for cache in candidates:
            if (cache / marker).exists():
                log.info("transcriber.reuse_cache", path=str(cache))
                return cache
        return self.settings.data_dir / "models"

    def load(self) -> None:
        from faster_whisper import WhisperModel
        cache = self._resolve_cache()
        cache.mkdir(parents=True, exist_ok=True)
        threads = min(8, max(2, os.cpu_count() or 4))

        attempts = [(self.model_size, self.device, self.compute_type)]
        if self.device == "cuda":
            attempts.append((self.model_size, "cuda", "int8_float16"))
            attempts.append(("small.en", "cpu", "int8"))
        elif self.model_size != "small.en":
            attempts.append(("small.en", "cpu", "int8"))

        last_exc: Exception | None = None
        start = time.monotonic()
        with self._lock:
            for name, device, compute in attempts:
                for local_only in (True, False):
                    try:
                        self._model = WhisperModel(
                            name, device=device, compute_type=compute,
                            local_files_only=local_only,
                            download_root=str(cache), cpu_threads=threads,
                            num_workers=2)
                        self.model_size, self.device, self.compute_type = name, device, compute
                        last_exc = None
                        break
                    except Exception as e:  # noqa: BLE001
                        last_exc = e
                if self._model is not None:
                    break
                log.warning("transcriber.rung_failed", model=name, device=device,
                            error=str(last_exc))
        if self._model is None:
            raise VoiceError(f"all whisper load attempts failed: {last_exc}")
        log.info("transcriber.ready", info=self.info,
                 seconds=round(time.monotonic() - start, 1))

    def transcribe(self, audio_f32: np.ndarray) -> str:
        if self._model is None:
            raise VoiceError("transcriber not loaded")
        beam = 5 if self.device == "cuda" else 5
        with self._lock:
            segments, _ = self._model.transcribe(
                audio_f32, language="en", beam_size=beam, best_of=5,
                initial_prompt=self.initial_prompt, vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 300, "speech_pad_ms": 80},
                condition_on_previous_text=False, temperature=0.0,
                no_speech_threshold=0.6, log_prob_threshold=-0.8,
                hallucination_silence_threshold=2.0)
            return " ".join(s.text.strip() for s in segments).strip()
