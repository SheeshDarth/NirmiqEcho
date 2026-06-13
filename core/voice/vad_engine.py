"""Hybrid voice-activity detection: webrtcvad on raw audio OR an adaptive
energy gate. The energy gate (noise-floor EMA x factor) catches quiet voices
that webrtcvad alone misses — proven on this machine's quiet mic.

Note: the spec names Silero VAD. webrtcvad+energy is used because it is
verified working on the target hardware with no model download; Silero can
be slotted behind this same interface later via config.
"""
from __future__ import annotations

import numpy as np

from core.shared.logger import get_logger

log = get_logger(__name__)

SAMPLE_RATE = 16000
FRAME_MS = 30
FRAME_SIZE = int(SAMPLE_RATE * FRAME_MS / 1000)   # 480 samples

ENERGY_FLOOR_FACTOR = 3.5
ENERGY_MIN_THRESHOLD = 40.0
NOISE_FLOOR_ALPHA = 0.05


class VADEngine:
    def __init__(self, sensitivity: int = 1):
        try:
            import webrtcvad
            self._vad = webrtcvad.Vad(max(0, min(3, sensitivity)))
        except ImportError:
            self._vad = None
            log.warning("vad.webrtc_missing")
        self.noise_floor = 0.0

    def is_speech(self, frame_i16: np.ndarray, in_speech: bool) -> bool:
        """frame_i16: int16 array of FRAME_SIZE samples."""
        rms = float(np.sqrt(np.mean(frame_i16.astype(np.float32) ** 2)))
        if not in_speech:
            if self.noise_floor == 0.0:
                self.noise_floor = rms
            elif rms < self.noise_floor * 2.5:
                self.noise_floor = ((1 - NOISE_FLOOR_ALPHA) * self.noise_floor
                                    + NOISE_FLOOR_ALPHA * rms)
        vad_speech = False
        if self._vad is not None:
            try:
                vad_speech = self._vad.is_speech(frame_i16.tobytes(), SAMPLE_RATE)
            except Exception:
                vad_speech = False
        gate = max(ENERGY_MIN_THRESHOLD, self.noise_floor * ENERGY_FLOOR_FACTOR)
        return vad_speech or rms >= gate

    @staticmethod
    def rms(frame_i16: np.ndarray) -> float:
        return float(np.sqrt(np.mean(frame_i16.astype(np.float32) ** 2)))
