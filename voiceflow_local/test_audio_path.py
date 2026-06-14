"""
test_audio_path.py — full audio→VAD→transcribe→command integration test

Feeds a real voice sample through the EXACT production chain with zero
mocking except the microphone hardware:

    .m4a  →  16kHz frames  →  AudioHandler._process_frame (real VAD)
          →  speech_queue  →  TranscriptionEngine (real Whisper)
          →  _on_result    →  PostProcessor + CommandProcessor

This is the chain that runs when you speak. If a sample transcribes and
routes here, the only remaining variable in the live app is the mic itself.

Usage: python test_audio_path.py ["optional command sample.m4a"]
"""
import sys
import time
import glob
import queue
import logging
from pathlib import Path

import numpy as np

logging.basicConfig(level=logging.WARNING, format="%(levelname)-7s %(name)-16s %(message)s")
log = logging.getLogger("audiopath")
log.setLevel(logging.INFO)

SAMPLES_DIR = Path(__file__).parent.parent


def load_pcm_16k(path: str) -> np.ndarray:
    """Decode any audio file to mono 16kHz float32 via faster-whisper's decoder."""
    from faster_whisper.audio import decode_audio
    return decode_audio(path, sampling_rate=16000)


def feed_through_vad(handler, pcm_f32: np.ndarray) -> int:
    """
    Push float32 audio through the REAL VAD state machine frame-by-frame,
    exactly as the mic callback does. Returns number of segments queued.
    """
    from audio_handler import FRAME_SIZE, VAD_SAMPLE_RATE

    int16 = np.clip(pcm_f32 * 32768.0, -32768, 32767).astype(np.int16)
    handler._running = True
    handler._reset_state()
    handler._noise_floor = 0.0
    handler._startup_frames = 999  # skip dead-mic check for file feed

    n_frames = len(int16) // FRAME_SIZE
    for i in range(n_frames):
        frame = int16[i * FRAME_SIZE:(i + 1) * FRAME_SIZE]
        raw = frame.tobytes()
        rms = float(np.sqrt(np.mean(frame.astype(np.float32) ** 2)))
        # adaptive noise floor (mirror of _audio_callback)
        if not handler._in_speech:
            if handler._noise_floor == 0.0:
                handler._noise_floor = rms
            elif rms < handler._noise_floor * 2.5:
                handler._noise_floor = 0.95 * handler._noise_floor + 0.05 * rms
        try:
            vad_speech = handler._vad.is_speech(raw, VAD_SAMPLE_RATE)
        except Exception:
            vad_speech = False
        from audio_handler import ENERGY_FLOOR_FACTOR, ENERGY_MIN_THRESHOLD
        gate = max(ENERGY_MIN_THRESHOLD, handler._noise_floor * ENERGY_FLOOR_FACTOR)
        is_speech = vad_speech or rms >= gate
        handler._process_frame(raw, is_speech)

    # flush trailing speech
    handler._flush_speech()
    # let the preprocess worker drain
    time.sleep(0.5)
    return handler.speech_queue.qsize()


def main():
    from audio_handler import AudioHandler
    from transcription import TranscriptionEngine
    from post_processor import PostProcessor
    from command_processor import CommandProcessor

    samples = sys.argv[1:] or sorted(glob.glob(str(SAMPLES_DIR / "Test*.m4a")))[:2]
    if not samples:
        print("No samples found")
        return

    print("Building real production stack (this loads Whisper)...")
    handler = AudioHandler(sensitivity=1)
    # start the preprocess worker so _flush_speech has somewhere to go
    import threading
    handler._preprocess_thread = threading.Thread(
        target=handler._preprocess_loop, daemon=True)
    handler._preprocess_thread.start()

    results = []
    engine = TranscriptionEngine(
        speech_queue=handler.speech_queue,
        on_result=lambda t: results.append(t),
        language="en",
    )
    engine.load_model()
    engine.start()

    pp = PostProcessor()
    cp = CommandProcessor()
    for _ in range(40):
        if cp._conv and cp._discovery:
            break
        time.sleep(0.1)

    print(f"Model: {engine.model_info}\n")

    for sample in samples:
        print(f"=== {Path(sample).name} ===")
        results.clear()
        pcm = load_pcm_16k(sample)
        dur = len(pcm) / 16000
        n_queued = feed_through_vad(handler, pcm)
        print(f"  {dur:.1f}s audio -> {n_queued} speech segment(s) reached the queue")

        # wait for transcription worker to produce results
        for _ in range(60):
            if results:
                break
            time.sleep(0.2)

        if not results:
            print("  RESULT: NO TRANSCRIPT — VAD or transcription failed\n")
            continue

        for raw in results:
            cleaned = pp.clean(raw)
            r = cp.process(cleaned) if cleaned else None
            print(f"  TRANSCRIPT: {raw!r}")
            if r:
                tag = "COMMAND" if r.is_command else "DICTATION"
                print(f"  ROUTED AS: {tag} (action={r.action})")
        print()

    engine.stop()
    print("Audio path test complete.")


if __name__ == "__main__":
    main()
