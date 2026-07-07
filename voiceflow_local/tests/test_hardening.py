"""Regression tests for Sprint-1 hardening.

Covers ``_safe_int`` — the defensive coercion that keeps a misheard number
("set volume to loud") from raising inside command dispatch. Pure and
cross-platform: it imports the helper only, never constructs CommandProcessor,
so it runs in CI too.
"""
from command_processor import _safe_int


def test_safe_int_parses_plain_number():
    assert _safe_int("30", 50, 0, 100) == 30


def test_safe_int_defaults_on_garbage():
    assert _safe_int("loud", 50, 0, 100) == 50
    assert _safe_int(None, 1, 1) == 1


def test_safe_int_extracts_embedded_digits():
    assert _safe_int("about 30 percent", 50, 0, 100) == 30


def test_safe_int_clamps_range():
    assert _safe_int("200", 50, 0, 100) == 100   # clamp to hi
    assert _safe_int("-5", 3, 1) == 1            # clamp to lo
