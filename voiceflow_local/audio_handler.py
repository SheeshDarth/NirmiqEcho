"""
audio_handler.py - Microphone capture and Voice Activity Detection (VAD)

Handles:
- Microphone stream using sounddevice
- Real-time VAD using webrtcvad (or webrtcvad-wheels — same API)
- Silence detection and speech segment extraction
- Thread-safe audio buffer management
"""

import os
import threading
import queue
import logging
from collections import deque
import numpy as np
import sounddevice as sd

try:
    import webrtcvad
except ImportError:
    raise ImportError(
        "webrtcvad not found. Install with:\n"
        "  pip install webrtcvad-wheels"
    )

try:
    import noisereduce as nr
    _NR_AVAILABLE = True
except ImportError:
    _NR_AVAILABLE = False

NOISE_REDUCE_STRENGTH = float(os.getenv("NOISE_REDUCE_STRENGTH", "0.65"))
GAIN_TARGET = 0.75    # conservative normalization — avoids amplifying residual noise

logger = logging.getLogger(__name__)

# VAD requires audio at specific sample rates
VAD_SAMPLE_RATE = 16000  # 16 kHz required by webrtcvad

# webrtcvad processes frames of 10ms, 20ms, or 30ms
FRAME_DURATION_MS = 30  # 30ms frames
FRAME_SIZE = int(VAD_SAMPLE_RATE * FRAME_DURATION_MS / 1000)  # 480 samples per frame

# Silence detection settings
SILENCE_THRESHOLD_FRAMES = 20   # 600ms of silence before flushing utterance
SPEECH_THRESHOLD_FRAMES = 2     # 60ms of voiced frames to confirm speech started (was 3)
MIN_SPEECH_FRAMES = 5           # minimum frames to consider a valid utterance
MAX_UTTERANCE_SECONDS = 30      # maximum single utterance length

# Background noise ring buffer — 2 s of pre-speech audio used as noise reference
BG_BUFFER_FRAMES = int(2.0 * 1000 / FRAME_DURATION_MS)  # 66 frames = 2 s

# ── Hybrid VAD (webrtcvad OR adaptive energy) ─────────────────────────
# webrtcvad runs on the RAW signal (boosting noise to speech level breaks
# its classifier). For quiet voices it is backed up by an energy gate with
# an adaptive noise floor: speech = vad(raw) OR rms > floor * FACTOR.
ENERGY_FLOOR_FACTOR  = 3.5    # speech must exceed noise floor by this ratio
ENERGY_MIN_THRESHOLD = 40.0   # absolute minimum energy gate (int16 RMS)
NOISE_FLOOR_ALPHA    = 0.05   # EMA rate for the noise floor estimate

# ── Dead-mic detection / device probing ───────────────────────────────
DEAD_MIC_RMS      = 3.0       # below this the device is considered silent
PROBE_SECONDS     = 1.0       # per-device probe length when scanning
PROBE_SKIP_SECONDS = 0.4      # discard driver spin-up silence at stream start
MIC_CHECK_FRAMES = 100        # ~3 s of frames to judge a dead mic at start
                              # (must outlast the spin-up window)


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
        # Rolling ring of recent non-speech frames — used as noise reference.
        # Never reset across utterances so the profile stays fresh.
        self._bg_frames: deque = deque(maxlen=BG_BUFFER_FRAMES)

        # State machine counters
        self._num_voiced = 0
        self._num_silent = 0
        self._in_speech = False

        # Audio level for UI feedback (0.0 - 1.0)
        self.audio_level = 0.0

        # Adaptive noise floor (EMA of quiet-frame RMS)
        self._noise_floor = 0.0

        # Dead-mic detection at stream start
        self._startup_frames = 0
        self._startup_peak_rms = 0.0
        self._mic_warned = False

        # Resolved input device (index or None = system default)
        self.input_device: int | None = None
        self.input_device_name: str = "system default"

        # Heavy DSP (noisereduce) must NOT run on the realtime audio
        # callback thread — it goes through this queue to a worker.
        self._preprocess_q: queue.Queue = queue.Queue()
        self._preprocess_thread: threading.Thread | None = None

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
        self._startup_frames = 0
        self._startup_peak_rms = 0.0
        self._mic_warned = False

        # Resolve the input device once per session (env override / probe)
        if self.input_device is None:
            self.input_device = self._resolve_input_device()

        # Start the preprocessing worker (noisereduce off the audio thread)
        if self._preprocess_thread is None or not self._preprocess_thread.is_alive():
            self._preprocess_thread = threading.Thread(
                target=self._preprocess_loop,
                name="AudioPreprocess",
                daemon=True,
            )
            self._preprocess_thread.start()

        logger.info("Opening microphone stream at %d Hz on device: %s",
                    VAD_SAMPLE_RATE, self.input_device_name)

        try:
            self._stream = sd.RawInputStream(
                samplerate=VAD_SAMPLE_RATE,
                channels=1,
                dtype="int16",
                blocksize=FRAME_SIZE,
                device=self.input_device,
                callback=self._audio_callback,
            )
            self._stream.start()
            self.on_status_change("listening")
            logger.info("Microphone stream started")
        except Exception as exc:
            self._running = False
            logger.error("Failed to open microphone: %s", exc)
            raise RuntimeError(f"Could not open microphone: {exc}") from exc

    # ------------------------------------------------------------------
    # Input device resolution
    # ------------------------------------------------------------------

    def _resolve_input_device(self) -> int | None:
        """
        Pick the input device:
          1. INPUT_DEVICE env (index or name substring) if set
          2. System default — unless it is dead silent (e.g. idle Bluetooth
             buds), in which case scan physical mics and pick the liveliest.
        Returns a device index, or None for system default.
        """
        devices = sd.query_devices()

        env = os.getenv("INPUT_DEVICE", "").strip()
        if env:
            if env.isdigit() and int(env) < len(devices) and \
                    devices[int(env)]["max_input_channels"] > 0:
                idx = int(env)
                self.input_device_name = devices[idx]["name"]
                logger.info("INPUT_DEVICE override: [%d] %s", idx, self.input_device_name)
                return idx
            for i, d in enumerate(devices):
                if d["max_input_channels"] > 0 and env.lower() in d["name"].lower():
                    self.input_device_name = d["name"]
                    logger.info("INPUT_DEVICE override: [%d] %s", i, d["name"])
                    return i
            logger.warning("INPUT_DEVICE %r not found — falling back to auto", env)

        # Probe the system default
        try:
            default_idx = sd.default.device[0]
        except Exception:
            default_idx = None

        if default_idx is not None and default_idx >= 0:
            rms = self._probe_device(default_idx)
            name = devices[default_idx]["name"]
            if rms < DEAD_MIC_RMS and self._ensure_mic_unmuted():
                # Windows-level mute was the culprit (mic-mute hotkey) —
                # unmuted it, probe again
                rms = self._probe_device(default_idx)
                logger.info("Re-probed default mic after unmute: rms %.1f", rms)
            if rms >= DEAD_MIC_RMS:
                self.input_device_name = name
                logger.info("Using default mic: [%d] %s (probe rms %.1f)",
                            default_idx, name, rms)
                return default_idx
            logger.warning(
                "Default mic '%s' is nearly silent (probe rms %.1f) — "
                "scanning for a live microphone", name, rms)

        # Scan physical mic candidates, dedupe by name prefix
        best_idx, best_rms = default_idx, -1.0
        seen: set[str] = set()
        for i, d in enumerate(devices):
            if d["max_input_channels"] == 0:
                continue
            name = d["name"]
            lname = name.lower()
            if not any(k in lname for k in ("microphone", "mic", "array", "headset")):
                continue
            if "sound mapper" in lname:
                continue
            key = lname[:24]
            if key in seen:
                continue
            seen.add(key)
            rms = self._probe_device(i)
            logger.info("  probe [%d] %s → rms %.1f", i, name[:50], rms)
            if rms > best_rms:
                best_idx, best_rms = i, rms

        if best_idx is not None and best_rms >= DEAD_MIC_RMS:
            self.input_device_name = devices[best_idx]["name"]
            logger.info("Auto-selected mic: [%d] %s (rms %.1f)",
                        best_idx, self.input_device_name, best_rms)
            return best_idx

        logger.error("No live microphone found — using system default. "
                     "Run mic_check.py to diagnose.")
        self.input_device_name = "system default (no live mic found)"
        return default_idx if (default_idx is not None and default_idx >= 0) else None

    @staticmethod
    def _probe_device(index: int) -> float:
        """
        Capture a short clip from a device and return its RMS (-1 on failure).
        The first PROBE_SKIP_SECONDS are discarded — mic arrays deliver
        silence while the driver spins up, which reads as a false dead mic.
        """
        try:
            frames = int(VAD_SAMPLE_RATE * PROBE_SECONDS)
            rec = sd.rec(frames, samplerate=VAD_SAMPLE_RATE, channels=1,
                         dtype="int16", device=index)
            sd.wait()
            skip = int(VAD_SAMPLE_RATE * PROBE_SKIP_SECONDS)
            pcm = rec.flatten()[skip:].astype(np.float32)
            if len(pcm) == 0:
                return -1.0
            return float(np.sqrt(np.mean(pcm ** 2)))
        except Exception as exc:
            logger.debug("probe device %d failed: %s", index, exc)
            return -1.0

    @staticmethod
    def _ensure_mic_unmuted() -> bool:
        """
        Unmute the default capture endpoint via Windows Core Audio (pycaw)
        and raise its level if it is very low. A pressed mic-mute hotkey
        silences EVERY app — this rescues Echo automatically.
        Returns True if the mute/level state was changed.
        """
        try:
            from pycaw.pycaw import (IAudioEndpointVolume, IMMDeviceEnumerator,
                                     EDataFlow, ERole)
            from pycaw.constants import CLSID_MMDeviceEnumerator
            from comtypes import CLSCTX_ALL, CoCreateInstance

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
                logger.warning("Default mic was MUTED at Windows level — unmuted it")
            if vol.GetMasterVolumeLevelScalar() < 0.40:
                vol.SetMasterVolumeLevelScalar(0.80, None)
                changed = True
                logger.warning("Default mic level was very low — raised to 80%%")
            return changed
        except Exception as exc:
            logger.debug("mic unmute check unavailable: %s", exc)
            return False

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

        # Flush any in-progress speech segment, then stop the worker
        self._flush_speech()
        if self._preprocess_thread is not None and self._preprocess_thread.is_alive():
            self._preprocess_q.put(None)
            self._preprocess_thread.join(timeout=3)
            self._preprocess_thread = None
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

        # Compute audio level for VU meter (uses raw signal)
        pcm = np.frombuffer(raw_bytes, dtype=np.int16)
        rms = float(np.sqrt(np.mean(pcm.astype(np.float32) ** 2)))
        self.audio_level = min(1.0, rms / 8000.0)

        # ── Dead-mic detection (first ~1.8 s of the stream) ──────────────
        if self._startup_frames < MIC_CHECK_FRAMES:
            self._startup_frames += 1
            self._startup_peak_rms = max(self._startup_peak_rms, rms)
            if (self._startup_frames == MIC_CHECK_FRAMES
                    and self._startup_peak_rms < DEAD_MIC_RMS
                    and not self._mic_warned):
                self._mic_warned = True
                logger.error(
                    "Microphone '%s' is delivering silence — wrong device or "
                    "muted. Run mic_check.py.", self.input_device_name)
                self.on_status_change("mic_dead")

        # ── Adaptive noise floor (EMA over quiet frames only) ────────────
        if not self._in_speech:
            if self._noise_floor == 0.0:
                self._noise_floor = rms
            elif rms < self._noise_floor * 2.5:
                self._noise_floor = ((1 - NOISE_FLOOR_ALPHA) * self._noise_floor
                                     + NOISE_FLOOR_ALPHA * rms)

        # ── Hybrid VAD: webrtcvad on RAW audio OR adaptive energy gate ───
        # (Never boost audio into webrtcvad — boosted noise classifies as
        # speech and the utterance never ends.)
        try:
            vad_speech = self._vad.is_speech(raw_bytes, VAD_SAMPLE_RATE)
        except Exception:
            vad_speech = False

        energy_gate = max(ENERGY_MIN_THRESHOLD,
                          self._noise_floor * ENERGY_FLOOR_FACTOR)
        is_speech = vad_speech or rms >= energy_gate

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

            if not self._in_speech:
                # Accumulate background noise as reference for noisereduce.
                # This is the only correct noise profile: real ambient audio
                # captured BEFORE speech started, not the speech itself.
                self._bg_frames.append(frame)
            else:
                # Buffer brief silences as trailing padding
                self._voiced_frames.append(frame)

                if self._num_silent >= SILENCE_THRESHOLD_FRAMES:
                    self._flush_speech()

    def _flush_speech(self) -> None:
        """
        Hand the buffered utterance to the preprocessing worker.
        Runs on the REALTIME audio callback thread — must stay cheap
        (byte joins only; noisereduce happens on the worker thread).
        """
        if not self._voiced_frames:
            self._reset_state()
            return

        if len(self._voiced_frames) < MIN_SPEECH_FRAMES:
            logger.debug("Utterance too short (%d frames), discarding", len(self._voiced_frames))
            self._reset_state()
            return

        speech_bytes = b"".join(self._voiced_frames)
        bg_bytes = b"".join(self._bg_frames) if self._bg_frames else b""

        self._preprocess_q.put((speech_bytes, bg_bytes))
        self.on_status_change("transcribing")
        self._reset_state()

    # ------------------------------------------------------------------
    # Preprocessing worker (denoise + normalize OFF the audio thread)
    # ------------------------------------------------------------------

    def _preprocess_loop(self) -> None:
        """Denoise + normalize utterances, then feed the transcription queue."""
        while True:
            item = self._preprocess_q.get()
            if item is None:
                break

            speech_bytes, bg_bytes = item
            pcm = np.frombuffer(speech_bytes, dtype=np.int16).astype(np.float32) / 32768.0

            # ── Spectral noise reduction ──────────────────────────────────
            # IMPORTANT: noise reference MUST be pre-speech background audio,
            # never the speech segment itself (which would subtract the voice).
            if _NR_AVAILABLE and bg_bytes:
                try:
                    bg_audio = (np.frombuffer(bg_bytes, dtype=np.int16)
                                .astype(np.float32) / 32768.0)
                    pcm = nr.reduce_noise(
                        y=pcm,
                        sr=VAD_SAMPLE_RATE,
                        y_noise=bg_audio,
                        prop_decrease=NOISE_REDUCE_STRENGTH,
                        stationary=False,
                        time_mask_smooth_ms=100,
                    )
                except Exception as exc:
                    logger.debug("noisereduce skipped: %s", exc)

            # ── Gain normalization — moderate boost for quiet voices ──────
            peak = float(np.max(np.abs(pcm)))
            if peak > 1e-6:
                pcm = pcm * (GAIN_TARGET / peak)

            logger.debug("Enqueuing speech segment: %.2f s", len(pcm) / VAD_SAMPLE_RATE)
            self.speech_queue.put(pcm)

        logger.debug("Preprocess worker exited")

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
