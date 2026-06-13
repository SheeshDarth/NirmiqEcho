"""Spectral noise suppression + gain normalisation.

The noise reference MUST be pre-speech background audio, never the speech
itself (that would subtract the voice) — a bug that cost real accuracy and
is deliberately prevented here.
"""
from __future__ import annotations

import numpy as np

from core.shared.logger import get_logger

log = get_logger(__name__)

try:
    import noisereduce as nr
    _NR = True
except ImportError:
    _NR = False

SAMPLE_RATE = 16000
GAIN_TARGET = 0.75       # normalise quiet voices to this peak


class NoiseSuppressor:
    def __init__(self, strength: float = 0.65):
        self.strength = strength

    def process(self, speech: np.ndarray, background: np.ndarray | None) -> np.ndarray:
        """speech/background are float32 in [-1, 1]. Returns cleaned float32."""
        out = speech
        if _NR and background is not None and len(background) > 0:
            try:
                out = nr.reduce_noise(
                    y=speech, sr=SAMPLE_RATE, y_noise=background,
                    prop_decrease=self.strength, stationary=False,
                    time_mask_smooth_ms=100,
                )
            except Exception as e:  # noqa: BLE001
                log.debug("noise.skip", error=str(e))
        peak = float(np.max(np.abs(out))) if len(out) else 0.0
        if peak > 1e-6:
            out = out * (GAIN_TARGET / peak)
        return out
