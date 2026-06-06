"""
post_processor.py - Text cleanup pipeline for NirmiqEcho transcriptions

Applied to every transcription result before display + typing.

Pipeline stages (each optional / configurable):
  1. Sentence casing   — capitalize first letter
  2. Filler removal    — strip "um", "uh", "like" etc.
  3. Accent correction — fix common mis-transcriptions for Indian English
  4. Punctuation fix   — ensure sentence ends with period if > 6 words
  5. Mode formatting   — note / message / search mode text shaping

Usage:
    pp = PostProcessor()
    clean = pp.clean("um so basically i was saying hello")
    # → "So basically I was saying hello."
"""

import re
import logging

logger = logging.getLogger(__name__)

# Words commonly mis-transcribed for Indian English speakers
# Format: "wrong pattern" → "correct text"
# These are derived from common Whisper errors on Indian English
ACCENT_CORRECTIONS: dict[str, str] = {
    r"\bwatsapp\b": "WhatsApp",
    r"\bwhat's app\b": "WhatsApp",
    r"\byoutube\b": "YouTube",
    r"\bgoogle\b": "Google",
    r"\binstagram\b": "Instagram",
    r"\biphone\b": "iPhone",
    r"\bandroid\b": "Android",
    r"\bwindows\b": "Windows",
    r"\bpython\b": "Python",
    r"\bjavascript\b": "JavaScript",
    r"\bgithub\b": "GitHub",
    r"\bai\b": "AI",
    r"\bml\b": "ML",
    r"\bapi\b": "API",
    r"\burl\b": "URL",
    r"\bhttp\b": "HTTP",
    r"\bui\b": "UI",
    r"\bux\b": "UX",
    # Common Indian English filler/style patterns Whisper gets wrong
    r"\b(i am|I am) having\b": "I have",           # "I am having" → "I have"
    r"\bkindly\b": "please",                         # formal register
    r"\bdo the needful\b": "handle this",            # Indian corporate phrase
    r"\bprepone\b": "reschedule to earlier",
    # Numbers spoken in Indian style
    r"\bone lakh\b": "100,000",
    r"\btwo lakhs\b": "200,000",
    r"\bone crore\b": "10,000,000",
}

# Filler words to strip (with surrounding context preserved)
FILLER_PATTERN = re.compile(
    r"\b(um+|uh+|hmm+|mm+|ahh?|err?|like\s+i\s+was\s+saying|you\s+know|"
    r"basically|actually|i\s+mean|so\s+basically|kind\s+of|sort\s+of)\b,?\s*",
    re.IGNORECASE,
)

# Sentence end detection
SENTENCE_END = re.compile(r"[.!?]$")


class PostProcessor:
    """
    Applies a configurable text-cleanup pipeline to raw Whisper output.

    Attributes:
        remove_fillers: Strip um/uh/basically etc. (default True)
        apply_accent_corrections: Fix brand names, Indian English patterns (default True)
        auto_punctuate: Add period if sentence has no end punctuation (default True)
        capitalize: Capitalize first word of output (default True)
    """

    def __init__(
        self,
        remove_fillers: bool = True,
        apply_accent_corrections: bool = True,
        auto_punctuate: bool = True,
        capitalize: bool = True,
    ):
        self.remove_fillers = remove_fillers
        self.apply_accent_corrections = apply_accent_corrections
        self.auto_punctuate = auto_punctuate
        self.capitalize = capitalize

        # Pre-compile accent correction patterns
        self._corrections = [
            (re.compile(pat, re.IGNORECASE), rep)
            for pat, rep in ACCENT_CORRECTIONS.items()
        ]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def clean(self, text: str) -> str:
        """Run the full cleanup pipeline on raw transcription text."""
        if not text or not text.strip():
            return text

        result = text.strip()

        # --- Stage 0: Hallucination detection (drop before any processing) ---
        if self._is_hallucination(result):
            logger.debug("PostProcessor: dropping hallucinated output: %r", result[:60])
            return ""

        if self.remove_fillers:
            result = self._strip_fillers(result)

        if self.apply_accent_corrections:
            result = self._apply_corrections(result)

        if self.capitalize:
            result = self._capitalize_first(result)

        if self.auto_punctuate:
            result = self._ensure_punctuation(result)

        # Collapse multiple spaces
        result = re.sub(r"  +", " ", result).strip()

        if result != text.strip():
            logger.debug("PostProcessor: '%s' → '%s'", text[:60], result[:60])

        return result

    @staticmethod
    def _is_hallucination(text: str) -> bool:
        """
        Detect Whisper hallucination patterns common with Indian English accents:
          - Syllable loops: "A.M.A.M.A.M." or "year-year-year-year"
          - Single token repeated many times
          - Extremely short outputs that are likely noise
        """
        # Pattern 1: dotted syllable loops like "A.M.A.M.A.M."
        if re.search(r"(\b\w{1,3}\.\s*){5,}", text):
            return True

        # Pattern 2: hyphenated word repetitions like "year-year-year-year"
        if re.search(r"\b(\w+)-\1(?:-\1){3,}", text):
            return True

        # Pattern 3: any word repeated 4+ times consecutively
        words = text.split()
        if len(words) >= 4:
            for i in range(len(words) - 3):
                if words[i] == words[i+1] == words[i+2] == words[i+3]:
                    return True

        # Pattern 4: text is more than 80% the same token
        if len(words) > 6:
            from collections import Counter
            most_common_word, count = Counter(words).most_common(1)[0]
            if count / len(words) > 0.6:
                return True

        return False


    def set_mode(self, mode: str) -> None:
        """
        Adjust pipeline for context:
          'note'    — add newlines between sentences, preserve all words
          'message' — inline, strip fillers aggressively
          'search'  — minimal cleanup, keep as raw as possible
          'default' — balanced
        """
        if mode == "note":
            self.remove_fillers = True
            self.auto_punctuate = True
        elif mode == "message":
            self.remove_fillers = True
            self.auto_punctuate = False   # let user decide message endings
        elif mode == "search":
            self.remove_fillers = True
            self.auto_punctuate = False
            self.capitalize = False
        else:
            self.remove_fillers = True
            self.auto_punctuate = True
            self.capitalize = True

    # ------------------------------------------------------------------
    # Pipeline stages
    # ------------------------------------------------------------------

    def _strip_fillers(self, text: str) -> str:
        cleaned = FILLER_PATTERN.sub("", text)
        # Clean up double spaces and leading/trailing commas
        cleaned = re.sub(r"^[,\s]+|[,\s]+$", "", cleaned)
        cleaned = re.sub(r"\s{2,}", " ", cleaned)
        return cleaned or text   # fall back to original if we stripped too much

    def _apply_corrections(self, text: str) -> str:
        for pattern, replacement in self._corrections:
            text = pattern.sub(replacement, text)
        return text

    @staticmethod
    def _capitalize_first(text: str) -> str:
        if not text:
            return text
        return text[0].upper() + text[1:]

    def _ensure_punctuation(self, text: str) -> str:
        stripped = text.rstrip()
        # Only add period for sentences with at least 4 words
        word_count = len(stripped.split())
        if word_count >= 4 and not SENTENCE_END.search(stripped):
            return stripped + "."
        return stripped


# ------------------------------------------------------------------
# Quick self-test
# ------------------------------------------------------------------

if __name__ == "__main__":
    pp = PostProcessor()
    tests = [
        "um so basically i was saying hello world",
        "can you open watsapp for me",
        "i am having a question about python",
        "search youtube for machine learning tutorials",
        "write a message to my friend",
        "so uh yeah this is a test",
        "open github and check my repositories",
    ]
    print("PostProcessor self-test:\n")
    for t in tests:
        cleaned = pp.clean(t)
        print(f"  IN : {t}")
        print(f"  OUT: {cleaned}")
        print()
