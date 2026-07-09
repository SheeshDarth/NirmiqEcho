"""
test_launch.py — verify the real app boots without crashing.

Instantiates NirmiqEchoApp and drives the startup sequence WITHOUT the
blocking tkinter mainloop, so we can confirm models load, the listener
starts, and the app reaches a ready+listening state. Auto-exits.
"""
import sys
import time
import threading
import logging

logging.basicConfig(level=logging.INFO,
                    format="%(levelname)-7s %(name)-16s %(message)s")
log = logging.getLogger("launch")


class FakeUI:
    """Stand-in for NirmiqEchoUI — records scheduled UI events, no tkinter."""
    def __init__(self):
        self.events = []
        self.audio_handler = None
    def schedule(self, cmd, *args):
        self.events.append((cmd, args))
    def run(self):
        pass


def main():
    from main import NirmiqEchoApp

    app = NirmiqEchoApp()
    app._autorun = True   # plug-and-play: start listening once model is ready

    # Build subsystems like run() does, but swap in the fake UI
    from accent_profile import AccentProfiler
    from post_processor import PostProcessor
    from command_processor import CommandProcessor
    from audio_handler import AudioHandler
    from transcription import TranscriptionEngine
    from wake_word import WakeWordDetector

    try:
        from tts_engine import TTSEngine
        app.tts_engine = TTSEngine()
        app.tts_engine.start()
    except Exception as e:
        log.warning("tts: %s", e)

    app.accent_profiler = AccentProfiler()
    app.post_processor = PostProcessor()
    app.command_processor = CommandProcessor(
        on_status_change=app._on_transcription_status,
        on_feedback=app._on_command_feedback)
    app.audio_handler = AudioHandler(sensitivity=1,
                                     on_status_change=app._on_audio_status)
    app.transcription_engine = TranscriptionEngine(
        speech_queue=app.audio_handler.speech_queue,
        on_result=app._on_result,
        on_status_change=app._on_transcription_status,
        language="en",
        initial_prompt=app.accent_profiler.initial_prompt)
    app.wake_word_detector = WakeWordDetector(
        on_wake=app._on_wake_word, on_status_change=app._on_wake_status)
    app.ui = FakeUI()
    app.ui.audio_handler = app.audio_handler

    log.info("=== Driving startup sequence ===")
    t0 = time.monotonic()
    app._startup_sequence()
    log.info("startup_sequence returned in %.1fs", time.monotonic() - t0)

    # Give it a moment to settle into listening
    time.sleep(3)

    states = [c for c, _ in app.ui.events if c == "set_status"]
    statuses = [a[0] for c, a in app.ui.events if c == "set_status"]
    print("\n=== STARTUP REPORT ===")
    print(f"  model ready:     {app.transcription_engine.is_ready}")
    print(f"  model info:      {app.transcription_engine.model_info}")
    print(f"  listening:       {app._listening}")
    print(f"  mic device:      {app.audio_handler.input_device_name}")
    print(f"  status events:   {statuses}")
    crashed = any(s == "error" for s in statuses)
    print(f"  RESULT: {'FAILED — error state' if crashed else 'BOOTS CLEAN'}")

    app.shutdown()
    sys.exit(1 if crashed else 0)


if __name__ == "__main__":
    main()
