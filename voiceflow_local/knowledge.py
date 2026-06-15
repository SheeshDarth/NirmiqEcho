"""
knowledge.py — spoken answers for NirmiqEcho ("real Jarvis" Q&A).

Turns "who is Einstein", "what is photosynthesis", "tell me about Mars" into a
short SPOKEN answer instead of just opening a browser search.

Resolution order:
  1. Wikipedia REST summary  — fast, factual, concise (needs internet,
     stdlib urllib, no extra dependency).
  2. Local Ollama model      — offline fallback for anything Wikipedia misses.
  3. None                    — caller falls back to a normal web search.
"""
from __future__ import annotations

import json
import logging
import re
import urllib.parse
import urllib.request

logger = logging.getLogger(__name__)

_TIMEOUT = 4.0
_WIKI = "https://en.wikipedia.org/api/rest_v1/page/summary/"

# Strip the question framing to get a clean topic for Wikipedia lookup.
_TOPIC_RE = re.compile(
    r"^(?:who|what|whats|what's|where|when|tell me about|"
    r"do you know(?: about)?|give me info on|info on)\s+"
    r"(?:is|are|was|were|the|a|an|about)?\s*",
    re.IGNORECASE)


def _topic(question: str) -> str:
    t = question.strip().rstrip("?.!").strip()
    t = _TOPIC_RE.sub("", t).strip()
    return t or question.strip().rstrip("?.!")


def _first_sentences(text: str, n: int = 2) -> str:
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return " ".join(parts[:n]).strip()


def _wikipedia(topic: str) -> str | None:
    try:
        url = _WIKI + urllib.parse.quote(topic.replace(" ", "_"))
        req = urllib.request.Request(url, headers={
            "User-Agent": "NirmiqEcho/1.0 (local voice assistant)"})
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        logger.debug("knowledge.wikipedia miss: %s", exc)
        return None
    # Skip disambiguation / missing pages
    if data.get("type", "").endswith("disambiguation"):
        return None
    extract = (data.get("extract") or "").strip()
    if not extract or len(extract) < 20:
        return None
    return _first_sentences(extract, 2)


def answer(question: str) -> str | None:
    """Return a short spoken answer, or None to let the caller web-search."""
    question = (question or "").strip()
    if not question:
        return None
    # 1. Wikipedia (concise + factual)
    wiki = _wikipedia(_topic(question))
    if wiki:
        return wiki
    # 2. Local LLM (offline) for everything else
    try:
        import llm_fallback
        return llm_fallback.ask(question, max_sentences=2)
    except Exception as exc:
        logger.debug("knowledge.llm miss: %s", exc)
        return None


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    for q in ["who is Albert Einstein", "what is photosynthesis",
              "tell me about the Eiffel Tower", "what is a black hole"]:
        print(f"\nQ: {q}\nA: {answer(q)}")
