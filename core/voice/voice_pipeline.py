"""Voice pipeline orchestrator.

mic → AudioCapture (VAD) → NoiseSuppressor → Transcriber → on_transcript

A background worker drains complete utterances, denoises (off the audio
thread), transcribes, applies the optional wake-word gate, and fires
on_transcript(text). State changes fire on_state(VoiceState) for the UI.

Run standalone:  python -m core.voice.voice_pipeline --test
"""
from __future__ import annotations

import argparse
import threading
import time
from typing import Callable, Optional

from core.shared.logger import configure_logging, get_logger
from core.shared.types import VoiceState
from .audio_capture import AudioCapture
from .microphone_profile import MicrophoneProfile
from .noise_suppressor import NoiseSuppressor
from .transcriber import Transcriber
from .vad_engine import VADEngine
from .wake_word import WakeWordGate

log = get_logger(__name__)


class VoicePipeline:
    def __init__(self,
                 on_transcript: Optional[Callable[[str], None]] = None,
                 on_state: Optional[Callable[[str], None]] = None,
                 on_level: Optional[Callable[[float], None]] = None,
                 wake_word: bool = False,
                 model_size: str | None = None):
        self._on_transcript = on_transcript or (lambda t: None)
        self._on_state = on_state or (lambda s: None)
        self._on_level = on_level or (lambda x: None)
        self.profile = MicrophoneProfile()
        self.vad = VADEngine(sensitivity=1)
        self.suppressor = NoiseSuppressor()
        self.transcriber = Transcriber(model_size=model_size)
        self.wake = WakeWordGate(enabled=wake_word)
        self._capture: AudioCapture | None = None
        self._worker: threading.Thread | None = None
        self._running = False

    @property
    def ready(self) -> bool:
        return self.transcriber.is_ready

    def load_model(self) -> None:
        self.transcriber.load()

    def start(self) -> None:
        if self._running:
            return
        if not self.transcriber.is_ready:
            self.transcriber.load()
        device = self.profile.resolve()
        self._capture = AudioCapture(
            device, self.vad,
            on_level=self._on_level,
            on_state=lambda s: self._on_state(s))
        self._running = True
        self._worker = threading.Thread(target=self._drain, daemon=True,
                                        name="voice-worker")
        self._worker.start()
        self._capture.start()
        log.info("pipeline.started", mic=self.profile.device_name,
                 model=self.transcriber.info)

    def stop(self) -> None:
        self._running = False
        if self._capture:
            self._capture.stop()

    def _drain(self) -> None:
        while self._running:
            if not self._capture:
                time.sleep(0.1)
                continue
            try:
                utt = self._capture.utterances.get(timeout=0.3)
            except Exception:
                continue
            try:
                audio = self.suppressor.process(utt.speech, utt.background)
                text = self.transcriber.transcribe(audio)
            except Exception as e:  # noqa: BLE001
                log.error("pipeline.transcribe_error", error=str(e))
                continue
            self._on_state(VoiceState.IDLE.value)
            if not text:
                continue
            passed, cleaned = self.wake.passes(text)
            if not passed:
                log.debug("pipeline.no_wake", text=text[:40])
                continue
            self._on_transcript(cleaned)


def _test() -> None:
    configure_logging("INFO")
    print("=== Voice pipeline --test ===")
    print("Loading model + resolving mic. Speak after 'listening'.")
    results = []

    def on_t(text: str):
        print(f"  TRANSCRIPT: {text!r}")
        results.append(text)

    def on_s(state: str):
        print(f"  [state] {state}")

    pipe = VoicePipeline(on_transcript=on_t, on_state=on_s)
    pipe.load_model()
    print(f"  model: {pipe.transcriber.info}")
    pipe.start()
    print(f"  mic: {pipe.profile.device_name}")
    print("  Listening for 20 seconds — say a few sentences...")
    try:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    pipe.stop()
    print(f"\n  Captured {len(results)} utterance(s). "
          f"{'PASS' if results else 'no speech detected'}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", action="store_true")
    args = parser.parse_args()
    if args.test:
        _test()
    else:
        print("Use --test to run the standalone capture+transcribe check.")
