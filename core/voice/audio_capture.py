"""Microphone capture: sounddevice stream → VAD state machine → utterances.

Runs on a background thread; produces complete speech segments (with a
pre-speech background buffer for the noise suppressor) onto a queue. Heavy
DSP and transcription happen downstream, never in the audio callback.
"""
from __future__ import annotations

import queue
import threading
from collections import deque

import numpy as np
import sounddevice as sd

from core.shared.logger import get_logger
from .vad_engine import FRAME_SIZE, SAMPLE_RATE, VADEngine

log = get_logger(__name__)

SPEECH_START_FRAMES = 2     # 60 ms of voiced frames to start
SILENCE_END_FRAMES = 50     # 1.5 s of silence ends an utterance
MIN_SPEECH_FRAMES = 5
MAX_UTTERANCE_FRAMES = int(30 * 1000 / 30)   # 30 s cap
BG_FRAMES = int(2.0 * 1000 / 30)             # 2 s background ring


class Utterance:
    __slots__ = ("speech", "background")

    def __init__(self, speech: np.ndarray, background: np.ndarray):
        self.speech = speech            # float32 [-1,1]
        self.background = background     # float32 [-1,1]


class AudioCapture:
    def __init__(self, device_index: int | None, vad: VADEngine,
                 on_level=None, on_state=None):
        self._device = device_index
        self._vad = vad
        self._on_level = on_level or (lambda x: None)
        self._on_state = on_state or (lambda s: None)
        self.utterances: queue.Queue[Utterance] = queue.Queue()
        self._stream: sd.RawInputStream | None = None
        self._running = False
        self._thread: threading.Thread | None = None
        self._frame_q: queue.Queue[bytes] = queue.Queue(maxsize=200)

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name="audio-capture")
        self._thread.start()
        self._stream = sd.RawInputStream(
            samplerate=SAMPLE_RATE, channels=1, dtype="int16",
            blocksize=FRAME_SIZE, device=self._device, callback=self._cb)
        self._stream.start()
        self._on_state("listening")
        log.info("capture.started", device=self._device)

    def stop(self) -> None:
        self._running = False
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        self._on_state("idle")

    def _cb(self, indata, frames, time_info, status):
        if not self._running:
            return
        try:
            self._frame_q.put_nowait(bytes(indata))
        except queue.Full:
            pass

    def _loop(self):
        voiced: list[bytes] = []
        bg = deque(maxlen=BG_FRAMES)
        in_speech = False
        silence = 0
        while self._running:
            try:
                raw = self._frame_q.get(timeout=0.3)
            except queue.Empty:
                continue
            frame = np.frombuffer(raw, dtype=np.int16)
            self._on_level(min(1.0, self._vad.rms(frame) / 8000.0))
            speech = self._vad.is_speech(frame, in_speech)

            if speech:
                if not in_speech:
                    voiced = [raw]
                    in_speech = True
                    silence = 0
                    self._on_state("vad_detected")
                else:
                    voiced.append(raw)
                if len(voiced) >= MAX_UTTERANCE_FRAMES:
                    self._flush(voiced, bg)
                    voiced, in_speech, silence = [], False, 0
            else:
                if in_speech:
                    voiced.append(raw)
                    silence += 1
                    if silence >= SILENCE_END_FRAMES:
                        self._flush(voiced, bg)
                        voiced, in_speech, silence = [], False, 0
                else:
                    bg.append(raw)

    def _flush(self, voiced: list[bytes], bg: deque):
        if len(voiced) < MIN_SPEECH_FRAMES:
            return
        speech = (np.frombuffer(b"".join(voiced), dtype=np.int16)
                  .astype(np.float32) / 32768.0)
        background = (np.frombuffer(b"".join(bg), dtype=np.int16)
                      .astype(np.float32) / 32768.0) if bg else np.array([], np.float32)
        self.utterances.put(Utterance(speech, background))
        self._on_state("transcribing")
