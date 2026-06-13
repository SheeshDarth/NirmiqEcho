"""Microphone resolution, auto-rescue, and per-mic profile persistence.

Ported from the hardened voiceflow_local audio handler (proven on this
machine: auto-unmutes a muted default mic, skips driver spin-up silence,
and picks a live device when the default is dead — e.g. idle Bluetooth buds).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

import numpy as np
import sounddevice as sd

from core.config.settings import get_settings
from core.shared.logger import get_logger

log = get_logger(__name__)

SAMPLE_RATE = 16000
DEAD_MIC_RMS = 3.0
PROBE_SECONDS = 1.0
PROBE_SKIP_SECONDS = 0.4   # discard driver spin-up silence


class MicrophoneProfile:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.device_index: Optional[int] = None
        self.device_name: str = "system default"
        self.noise_floor: float = 0.0
        self.rms_baseline: float = 0.0
        self._profile_path = self.settings.data_dir / "mic_profile.json"

    # ── resolution ────────────────────────────────────────────────────

    def resolve(self) -> Optional[int]:
        """Pick the input device: env override > live default > scan."""
        devices = sd.query_devices()
        env = (self.settings.voice.input_device or
               os.getenv("NIRMIQ_INPUT_DEVICE", "")).strip()
        if env:
            idx = self._match_env(env, devices)
            if idx is not None:
                self.device_index = idx
                self.device_name = devices[idx]["name"]
                return idx

        try:
            default_idx = sd.default.device[0]
        except Exception:
            default_idx = None

        if default_idx is not None and default_idx >= 0:
            rms = self._probe(default_idx)
            if rms < DEAD_MIC_RMS and self._unmute_default():
                rms = self._probe(default_idx)
            if rms >= DEAD_MIC_RMS:
                self.device_index = default_idx
                self.device_name = devices[default_idx]["name"]
                log.info("mic.default", name=self.device_name, rms=round(rms, 1))
                return default_idx
            log.warning("mic.default_silent", rms=round(rms, 1))

        best_idx, best_rms, seen = default_idx, -1.0, set()
        for i, d in enumerate(devices):
            if d["max_input_channels"] == 0:
                continue
            name = (d["name"] or "").lower()
            if not any(k in name for k in ("microphone", "mic", "array", "headset")):
                continue
            if "sound mapper" in name or name[:24] in seen:
                continue
            seen.add(name[:24])
            rms = self._probe(i)
            if rms > best_rms:
                best_idx, best_rms = i, rms
        if best_idx is not None and best_rms >= DEAD_MIC_RMS:
            self.device_index = best_idx
            self.device_name = devices[best_idx]["name"]
            log.info("mic.scanned", name=self.device_name, rms=round(best_rms, 1))
            return best_idx

        log.error("mic.none_live")
        self.device_index = default_idx if (default_idx and default_idx >= 0) else None
        return self.device_index

    @staticmethod
    def _match_env(env: str, devices) -> Optional[int]:
        if env.isdigit() and int(env) < len(devices) and \
                devices[int(env)]["max_input_channels"] > 0:
            return int(env)
        for i, d in enumerate(devices):
            if d["max_input_channels"] > 0 and env.lower() in (d["name"] or "").lower():
                return i
        return None

    @staticmethod
    def _probe(index: int) -> float:
        try:
            frames = int(SAMPLE_RATE * PROBE_SECONDS)
            rec = sd.rec(frames, samplerate=SAMPLE_RATE, channels=1,
                         dtype="int16", device=index)
            sd.wait()
            skip = int(SAMPLE_RATE * PROBE_SKIP_SECONDS)
            pcm = rec.flatten()[skip:].astype(np.float32)
            return float(np.sqrt(np.mean(pcm ** 2))) if len(pcm) else -1.0
        except Exception as e:  # noqa: BLE001
            log.debug("mic.probe_failed", index=index, error=str(e))
            return -1.0

    @staticmethod
    def _unmute_default() -> bool:
        """Undo a Windows-level mic mute (mic-mute hotkey) via Core Audio."""
        try:
            from comtypes import CLSCTX_ALL, CoCreateInstance
            from pycaw.constants import CLSID_MMDeviceEnumerator
            from pycaw.pycaw import (EDataFlow, ERole, IAudioEndpointVolume,
                                     IMMDeviceEnumerator)
            enum = CoCreateInstance(CLSID_MMDeviceEnumerator,
                                    IMMDeviceEnumerator, CLSCTX_ALL)
            dev = enum.GetDefaultAudioEndpoint(EDataFlow.eCapture.value,
                                               ERole.eConsole.value)
            vol = dev.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL,
                               None).QueryInterface(IAudioEndpointVolume)
            changed = False
            if vol.GetMute():
                vol.SetMute(0, None)
                changed = True
                log.warning("mic.unmuted")
            if vol.GetMasterVolumeLevelScalar() < 0.40:
                vol.SetMasterVolumeLevelScalar(0.80, None)
                changed = True
            return changed
        except Exception as e:  # noqa: BLE001
            log.debug("mic.unmute_unavailable", error=str(e))
            return False

    # ── persistence ───────────────────────────────────────────────────

    def save(self) -> None:
        data = {"device_index": self.device_index, "device_name": self.device_name,
                "noise_floor": self.noise_floor, "rms_baseline": self.rms_baseline}
        self._profile_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def load(self) -> bool:
        if not self._profile_path.exists():
            return False
        try:
            data = json.loads(self._profile_path.read_text(encoding="utf-8"))
            self.device_index = data.get("device_index")
            self.device_name = data.get("device_name", "system default")
            self.noise_floor = data.get("noise_floor", 0.0)
            return True
        except Exception:  # noqa: BLE001
            return False
