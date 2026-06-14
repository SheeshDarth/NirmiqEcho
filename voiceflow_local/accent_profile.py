"""
accent_profile.py - Voice sample analysis and accent-aware initial_prompt builder

Analyses user voice recordings with Whisper to extract:
  - Language / accent detection
  - Common phonetic patterns and vocabulary
  - Speech rate and rhythm characteristics

Produces an `initial_prompt` string injected into every Whisper transcription
call to prime the model for the user's specific voice and accent.

Profile is saved to assets/accent_profile.json and reloaded on startup
(analysis only runs once, or when the user provides new samples).
"""

import json
import logging
import os
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

PROFILE_PATH = Path(__file__).parent / "assets" / "accent_profile.json"

# Default profile used before analysis or if analysis fails
DEFAULT_PROFILE = {
    "language": "en",
    "language_probability": 0.95,
    "accent_hint": "Indian English",
    "initial_prompt": (
        "The following is a voice transcription of Indian English speech. "
        "The speaker has a clear Indian accent with standard English vocabulary. "
        "Transcribe accurately including technical terms."
    ),
    "sample_texts": [],
    "analyzed_at": None,
    "version": 1,
}


class AccentProfiler:
    """
    One-time voice analysis that builds a personalized Whisper initial_prompt.

    Usage:
        profiler = AccentProfiler()
        profiler.analyze(["Test 1 voice.m4a", "Test 2.m4a", ...])
        prompt = profiler.initial_prompt   # inject into TranscriptionEngine
    """

    def __init__(self):
        self._profile: dict = {}
        self._load_or_default()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def initial_prompt(self) -> str:
        return self._profile.get("initial_prompt", DEFAULT_PROFILE["initial_prompt"])

    @property
    def language(self) -> str:
        return self._profile.get("language", "en")

    @property
    def is_analyzed(self) -> bool:
        return bool(self._profile.get("analyzed_at"))

    def analyze(self, audio_files: list[str], force: bool = False) -> bool:
        """
        Transcribe voice samples and extract accent characteristics.

        Args:
            audio_files: Paths to .m4a/.wav/.mp3 voice recordings.
            force: Re-run even if a profile already exists.

        Returns:
            True if analysis succeeded and profile was saved.
        """
        existing_files = [f for f in audio_files if Path(f).exists()]
        if not existing_files:
            logger.warning("AccentProfiler: no audio files found, using default profile")
            return False

        if self.is_analyzed and not force:
            logger.info("AccentProfiler: using existing profile from %s",
                        self._profile.get("analyzed_at"))
            return True

        logger.info("AccentProfiler: analysing %d voice samples…", len(existing_files))

        try:
            from faster_whisper import WhisperModel

            # Use tiny model for speed — good enough for language/accent detection
            model = WhisperModel("tiny", device="cpu", compute_type="int8",
                                  local_files_only=False)

            all_texts: list[str] = []
            languages: list[str] = []
            lang_probs: list[float] = []

            for fpath in existing_files:
                logger.info("  Analysing: %s", Path(fpath).name)
                try:
                    segments, info = model.transcribe(
                        fpath,
                        beam_size=5,
                        language=None,       # auto-detect per file
                        word_timestamps=False,
                        vad_filter=True,
                        temperature=0.0,
                        no_speech_threshold=0.3,
                    )
                    text = " ".join(s.text for s in segments).strip()
                    if text:
                        all_texts.append(text)
                        languages.append(info.language)
                        lang_probs.append(info.language_probability)
                        logger.info("    → [%s %.0f%%] %s",
                                    info.language, info.language_probability * 100,
                                    text[:80])
                except Exception as exc:
                    logger.warning("  Failed to analyse %s: %s", fpath, exc)

            if not all_texts:
                logger.error("AccentProfiler: no text extracted from samples")
                return False

            # Determine dominant language
            dominant_lang = max(set(languages), key=languages.count) if languages else "en"
            avg_prob = sum(lang_probs) / len(lang_probs) if lang_probs else 0.9

            # Build personalized initial_prompt
            prompt = self._build_prompt(all_texts, dominant_lang)

            self._profile = {
                "language": dominant_lang,
                "language_probability": round(avg_prob, 3),
                "accent_hint": self._detect_accent_hint(all_texts, dominant_lang),
                "initial_prompt": prompt,
                "sample_texts": [t[:200] for t in all_texts],
                "analyzed_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "version": 1,
            }

            self._save()
            logger.info("AccentProfiler: profile saved → %s", PROFILE_PATH)
            return True

        except Exception as exc:
            logger.error("AccentProfiler: analysis failed: %s", exc, exc_info=True)
            return False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_prompt(self, sample_texts: list[str], language: str) -> str:
        """
        Construct an initial_prompt that primes Whisper for the user's voice.

        The prompt serves two purposes:
          1. Tell Whisper what kind of speech to expect (accent, domain, style)
          2. Provide example vocabulary/phrases that appear in the samples
             so the model's context window is tuned.
        """
        # Collect unique meaningful words from samples (longer = more distinctive)
        all_words: list[str] = []
        for text in sample_texts:
            words = [w.strip(".,!?;:\"'()[]") for w in text.split()]
            all_words.extend([w for w in words if len(w) > 4])

        # Pick top-20 most frequent distinctive words as vocabulary hints
        from collections import Counter
        word_freq = Counter(w.lower() for w in all_words)
        # Remove very common English stop words
        stop = {"their", "there", "about", "which", "would", "could", "should",
                "these", "those", "because", "through", "before", "after",
                "other", "where", "while", "being", "every", "using", "will",
                "have", "that", "this", "with", "from", "they", "them", "then",
                "when", "than", "just", "also", "some", "been", "what", "your"}
        vocab_hints = [w for w, _ in word_freq.most_common(30)
                       if w not in stop and w.isalpha()][:15]

        # Detect if predominantly Indian English
        accent_context = self._detect_accent_hint(sample_texts, language)

        # Combine into a natural-sounding prompt paragraph
        vocab_str = ", ".join(vocab_hints) if vocab_hints else ""

        prompt_parts = [
            f"This is a voice transcription of {accent_context} speech.",
            "The speaker uses clear diction with standard English vocabulary.",
        ]

        if vocab_str:
            prompt_parts.append(
                f"Common terms used by this speaker include: {vocab_str}."
            )

        prompt_parts += [
            "Transcribe exactly what is said, preserving technical terms and proper nouns.",
            "Do not add punctuation not present in speech.",
        ]

        return " ".join(prompt_parts)

    @staticmethod
    def _detect_accent_hint(texts: list[str], language: str) -> str:
        """Heuristically determine accent description for the prompt."""
        combined = " ".join(texts).lower()

        # Detect Indian English patterns
        indian_markers = [
            "actually", "only", "itself", "basically", "obviously",
            "proper", "good", "nice", "right", "okay", "yes yes",
        ]
        indian_score = sum(1 for m in indian_markers if m in combined)

        if language == "en" and indian_score >= 2:
            return "Indian English"
        elif language == "hi":
            return "Hindi-accented English"
        elif language == "en":
            return "English"
        else:
            return f"{language.upper()} accented English"

    def _load_or_default(self) -> None:
        """Load existing profile from disk, or use defaults."""
        if PROFILE_PATH.exists():
            try:
                with open(PROFILE_PATH, "r", encoding="utf-8") as f:
                    self._profile = json.load(f)
                logger.info("AccentProfiler: loaded profile from %s", PROFILE_PATH)
                return
            except Exception as exc:
                logger.warning("AccentProfiler: could not load profile: %s", exc)

        logger.info("AccentProfiler: no profile found — using default Indian English prompt")
        self._profile = DEFAULT_PROFILE.copy()

    def _save(self) -> None:
        """Persist profile to disk."""
        PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(PROFILE_PATH, "w", encoding="utf-8") as f:
            json.dump(self._profile, f, indent=2, ensure_ascii=False)


# ------------------------------------------------------------------
# Standalone runner — call directly to re-analyse samples
# ------------------------------------------------------------------

def run_analysis(sample_dir: str | None = None) -> None:
    """Re-analyse all voice samples and regenerate the accent profile."""
    import glob
    if sample_dir is None:
        # Project root (parent of voiceflow_local), where Test*.m4a live.
        sample_dir = str(Path(__file__).resolve().parent.parent)
    files = glob.glob(f"{sample_dir}/Test *.m4a") + glob.glob(f"{sample_dir}/Test*.wav")
    files.sort()

    if not files:
        print(f"No test recording files found in {sample_dir}")
        return

    print(f"Found {len(files)} voice samples:")
    for f in files:
        print(f"  {f}")

    profiler = AccentProfiler()
    ok = profiler.analyze(files, force=True)

    if ok:
        print("\n[OK] Accent profile generated:")
        print(f"   Language : {profiler.language}")
        print(f"   Prompt   : {profiler.initial_prompt[:100]}...")
        print(f"   Saved to : {PROFILE_PATH}")
    else:
        print("\n[FAILED] Analysis failed -- using default profile")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s  %(levelname)-8s  %(message)s")
    run_analysis()
