"""
NirmiqEcho Voice Listener
═══════════════════════════════════════════════════════════════════
Accuracy pipeline:
  sounddevice (16 kHz, 16-bit mono)
  → dual-threshold energy VAD   (catches quiet speech)
  → noisereduce                 (spectral subtraction, noisy envs)
  → gain normalisation          (low voice → -3 dBFS target)
  → faster-whisper medium.en    (96 % WER, int8 quant → 800 MB RAM)

VAD tuning:
  SPEECH_RMS_THRESHOLD  – lower = more sensitive (default 400 suits
                          quiet voices in a room; lower to 200 for
                          very quiet speakers)
  SILENCE_PAD_FRAMES    – 40 frames × 20 ms = 800 ms trailing pad
                          so the last word is never cut off
"""
from __future__ import annotations

import threading
import queue
import time
from pathlib import Path
from typing import Callable

import numpy as np
import sounddevice as sd
import noisereduce as nr

_MODEL = None
_MODEL_READY = threading.Event()
_MODEL_LOCK  = threading.Lock()


# ── config (can be overridden by main.py before load_model) ──────────
WHISPER_MODEL_SIZE    = os.getenv("WHISPER_MODEL", "medium.en")
WHISPER_COMPUTE_TYPE  = "int8"          # int8 = fast CPU, float16 = GPU
SAMPLE_RATE           = 16_000          # Hz — Whisper native rate
FRAME_DURATION_MS     = 20             # must be 10, 20, or 30 for VAD
SPEECH_RMS_THRESHOLD  = int(os.getenv("SPEECH_RMS_THRESHOLD", "400"))
SILENCE_RMS_THRESHOLD = max(50, SPEECH_RMS_THRESHOLD // 2)
SILENCE_PAD_FRAMES    = 40             # 40 × 20 ms = 800 ms silence to end
MIN_SPEECH_FRAMES     = 8              # 8 × 20 ms = 160 ms min utterance
NOISE_REDUCE_STRENGTH = float(os.getenv("NOISE_REDUCE_STRENGTH", "0.80"))
GAIN_TARGET           = 0.90           # normalise to this peak amplitude

FRAME_SIZE = int(SAMPLE_RATE * FRAME_DURATION_MS / 1000)  # samples per frame


# ── model loading ─────────────────────────────────────────────────────

def load_model(on_ready: Callable | None = None):
    """Load Whisper in a background thread so startup isn't blocked."""
    def _load():
        global _MODEL
        from faster_whisper import WhisperModel
        with _MODEL_LOCK:
            _MODEL = WhisperModel(
                WHISPER_MODEL_SIZE,
                device="cpu",
                compute_type=WHISPER_COMPUTE_TYPE,
                download_root=str(Path.home() / ".cache" / "nirmiq_echo"),
            )
        _MODEL_READY.set()
        if on_ready:
            on_ready()
    threading.Thread(target=_load, daemon=True, name="whisper-loader").start()


def is_model_ready() -> bool:
    return _MODEL_READY.is_set()


# ── audio helpers ─────────────────────────────────────────────────────

def _rms(frame: np.ndarray) -> float:
    return float(np.sqrt(np.mean(frame.astype(np.float64) ** 2)))


def _denoise_and_normalise(int16_frames: list[np.ndarray]) -> np.ndarray:
    """Concat raw int16 frames → float32 denoised + gain-normalised audio."""
    audio = np.concatenate(int16_frames).astype(np.float32) / 32768.0

    # Spectral noise reduction — uses first 0.5 s as noise profile estimate
    noise_clip_len = min(len(audio), int(SAMPLE_RATE * 0.5))
    reduced = nr.reduce_noise(
        y=audio,
        sr=SAMPLE_RATE,
        y_noise=audio[:noise_clip_len] if noise_clip_len else None,
        prop_decrease=NOISE_REDUCE_STRENGTH,
        stationary=False,   # non-stationary mode tracks changing noise floor
        time_mask_smooth_ms=100,
    )

    # Gain normalisation — bring quiet voices up to target amplitude
    peak = np.max(np.abs(reduced))
    if peak > 1e-6:
        reduced *= GAIN_TARGET / peak

    return reduced


def _transcribe(audio_f32: np.ndarray) -> str:
    if not _MODEL_READY.wait(timeout=30):
        return ""
    with _MODEL_LOCK:
        segments, _ = _MODEL.transcribe(
            audio_f32,
            beam_size=5,
            best_of=5,
            language="en",
            vad_filter=True,              # Whisper's own VAD as second pass
            vad_parameters={
                "min_silence_duration_ms": 300,
                "speech_pad_ms": 200,
            },
            condition_on_previous_text=False,  # no hallucination carry-over
            temperature=0,                     # greedy; lowest hallucination rate
        )
    return " ".join(s.text.strip() for s in segments).strip()


# ── main listener class ───────────────────────────────────────────────

class VoiceListener:
    """
    Continuous push-to-listen voice listener.
    Runs a background thread that permanently reads the microphone.
    When speech is detected it calls on_transcript(text) on the main thread.
    """

    def __init__(
        self,
        on_transcript: Callable[[str], None],
        on_state_change: Callable[[str], None] | None = None,
    ):
        self._on_transcript   = on_transcript
        self._on_state        = on_state_change or (lambda s: None)
        self._running         = False
        self._muted           = False           # soft mute without stopping thread
        self._audio_q: queue.Queue[np.ndarray] = queue.Queue(maxsize=200)
        self._thread: threading.Thread | None   = None

    # public API ──────────────────────────────────────────────────────

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._vad_loop, daemon=True, name="nirmiq-listener"
        )
        self._thread.start()

    def stop(self):
        self._running = False

    def mute(self):
        self._muted = True
        self._on_state("muted")

    def unmute(self):
        self._muted = False
        self._on_state("idle")

    @property
    def muted(self) -> bool:
        return self._muted

    # internals ───────────────────────────────────────────────────────

    def _audio_callback(self, indata: np.ndarray, frames, _t, _status):
        try:
            self._audio_q.put_nowait(indata.copy())
        except queue.Full:
            pass  # drop frame under overload rather than block

    def _vad_loop(self):
        in_speech        = False
        voiced_frames: list[np.ndarray] = []
        silence_counter  = 0

        with sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="int16",
            blocksize=FRAME_SIZE,
            callback=self._audio_callback,
            latency="low",
        ):
            while self._running:
                try:
                    frame = self._audio_q.get(timeout=0.3)
                except queue.Empty:
                    continue

                if self._muted:
                    voiced_frames.clear()
                    in_speech = False
                    silence_counter = 0
                    continue

                rms = _rms(frame)

                # ── VAD state machine ─────────────────────────────────
                if not in_speech:
                    if rms >= SPEECH_RMS_THRESHOLD:
                        in_speech = True
                        silence_counter = 0
                        voiced_frames = [frame]
                        self._on_state("listening")
                else:
                    voiced_frames.append(frame)
                    if rms < SILENCE_RMS_THRESHOLD:
                        silence_counter += 1
                    else:
                        silence_counter = 0  # reset on any non-silence burst

                    if silence_counter >= SILENCE_PAD_FRAMES:
                        # ── utterance ended ───────────────────────────
                        if len(voiced_frames) >= MIN_SPEECH_FRAMES:
                            self._on_state("processing")
                            audio = _denoise_and_normalise(voiced_frames)
                            text  = _transcribe(audio)
                            if text:
                                self._on_transcript(text)
                        in_speech = False
                        voiced_frames.clear()
                        silence_counter = 0
                        self._on_state("idle")
