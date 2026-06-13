"""Optional wake-word gate. Checks whether a transcript begins with the
configured wake word (default "nirmiq"). A lightweight, dependency-free
approach that works on the transcript we already produce; openWakeWord can
be slotted in later behind this same interface.
"""
from __future__ import annotations

import re

from core.config.settings import get_settings
from core.shared.logger import get_logger

log = get_logger(__name__)


class WakeWordGate:
    def __init__(self, enabled: bool = False):
        self.settings = get_settings()
        self.enabled = enabled
        self.word = (self.settings.voice.wake_word or "nirmiq").lower()

    def passes(self, transcript: str) -> tuple[bool, str]:
        """
        Returns (passed, cleaned_transcript). When disabled, always passes.
        When enabled, requires the wake word near the start and strips it.
        """
        if not self.enabled:
            return True, transcript
        low = transcript.lower().strip()
        # accept "nirmiq, ...", "hey nirmiq ...", small ASR variants
        m = re.match(rf"^(?:hey\s+|ok\s+)?{re.escape(self.word)}[\s,.:]*", low)
        if m:
            cleaned = transcript[m.end():].strip()
            return True, cleaned or transcript
        return False, transcript
