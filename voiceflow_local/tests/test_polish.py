"""MS2 dictation-polish: offline-safe behavior of llm_fallback.polish().

The live "rambly speech -> clean sentence" rewrite needs a running Ollama and
so lives in the manual suite. What CI must guarantee is the OFFLINE contract:
when Ollama is down (or the text isn't worth a round-trip) polish() returns
None, so the dictation path keeps the fast rules-cleaned text and never blocks.
Pure stdlib (urllib) — cross-platform, runs in CI.
"""
import llm_fallback
from post_processor import PostProcessor


def test_polish_returns_none_when_ollama_unavailable(monkeypatch):
    monkeypatch.setattr(llm_fallback, "is_available", lambda: False)
    assert llm_fallback.polish("um so basically i was saying hello there") is None


def test_polish_skips_tiny_input_without_calling_ollama(monkeypatch):
    # Length guard runs BEFORE availability, so this must not touch the network.
    def _boom():
        raise AssertionError("is_available must not be reached for tiny input")
    monkeypatch.setattr(llm_fallback, "is_available", _boom)
    assert llm_fallback.polish("hello") is None


def test_dictation_still_yields_text_with_llm_off():
    # The offline guarantee: with polish() a no-op, the rules cleaner still turns
    # real speech into usable typed text (never empty).
    cleaned = PostProcessor().clean("um so basically i was saying hello there")
    assert cleaned
