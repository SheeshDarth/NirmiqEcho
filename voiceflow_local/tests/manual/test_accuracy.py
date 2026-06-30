"""
test_accuracy.py — End-to-end transcription accuracy test for NirmiqEcho

Runs the user's real voice samples through the EXACT same pipeline settings
that TranscriptionEngine uses in production (large-v3, beam_size=8, best_of=5,
accent initial_prompt, VAD filter), and prints results + timing.

Usage:  python test_accuracy.py [model_size] [beam_size]
        model_size defaults to large-v3, beam_size defaults to 8
"""

import sys
import time
import glob
from pathlib import Path

SAMPLES_DIR = Path(__file__).parent.parent       # Voice-text/
MODELS_DIR = SAMPLES_DIR / "models"


def main():
    model_size = sys.argv[1] if len(sys.argv) > 1 else "large-v3"
    beam_size = int(sys.argv[2]) if len(sys.argv) > 2 else 8

    samples = sorted(glob.glob(str(SAMPLES_DIR / "Test*.m4a")))
    if not samples:
        print("No Test*.m4a samples found in", SAMPLES_DIR)
        sys.exit(1)

    print(f"Model: {model_size}  |  beam_size: {beam_size}  |  Samples: {len(samples)}")
    print("Loading model from local cache...")

    from faster_whisper import WhisperModel
    t0 = time.monotonic()
    model = WhisperModel(
        model_size,
        device="cpu",
        compute_type="int8",
        local_files_only=True,
        download_root=str(MODELS_DIR),
        cpu_threads=8,
    )
    print(f"Model loaded in {time.monotonic() - t0:.1f}s\n")

    # Same accent prompt the production engine uses
    sys.path.insert(0, str(Path(__file__).parent))
    from accent_profile import AccentProfiler
    prompt = AccentProfiler().initial_prompt

    total_audio = 0.0
    total_time = 0.0

    for fpath in samples:
        name = Path(fpath).name
        t0 = time.monotonic()
        segments, info = model.transcribe(
            fpath,
            language="en",
            beam_size=beam_size,
            best_of=5,
            initial_prompt=prompt,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 300, "speech_pad_ms": 80},
            condition_on_previous_text=False,
            temperature=0.0,
            no_speech_threshold=0.6,
            log_prob_threshold=-0.8,
            hallucination_silence_threshold=2.0,
        )
        text = " ".join(s.text.strip() for s in segments).strip()
        elapsed = time.monotonic() - t0
        total_audio += info.duration
        total_time += elapsed

        print(f"=== {name}  ({info.duration:.1f}s audio, {elapsed:.1f}s transcribe, "
              f"lang_prob={info.language_probability:.2f}) ===")
        print(f"  {text}\n")

    rtf = total_time / total_audio if total_audio else 0
    print(f"TOTAL: {total_audio:.0f}s audio in {total_time:.0f}s "
          f"(real-time factor: {rtf:.2f}x)")


if __name__ == "__main__":
    main()
