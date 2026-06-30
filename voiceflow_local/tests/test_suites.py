"""Pytest wrappers around NirmiqEcho's existing offline check suites.

Each legacy suite is a standalone script that exits ``0`` on pass and non-zero on
failure. Rather than rewrite their assertions, we run each as its own subprocess
— exactly as invoking it by hand — and assert a clean exit. Running them isolated
(not imported in-process) avoids shared TTS / COM / audio re-initialisation
across suites.

Suites that construct ``CommandProcessor`` touch ``winreg`` and audio devices, so
they are Windows-only and skipped elsewhere (e.g. Linux CI), where the pure-logic
suites still run — preserving the exact CI coverage that existed before pytest.
"""
import subprocess
import sys
from pathlib import Path

import pytest

VOICEFLOW = Path(__file__).resolve().parent.parent  # the voiceflow_local/ dir

windows_only = pytest.mark.skipif(
    sys.platform != "win32",
    reason="constructs CommandProcessor (winreg / audio) — Windows only",
)


def _run(script: str) -> None:
    """Run a suite script in its own process (cwd = voiceflow_local) and assert it passes."""
    proc = subprocess.run(
        [sys.executable, script],
        cwd=str(VOICEFLOW),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, (
        f"{script} exited {proc.returncode}\n"
        f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
    )


# ── cross-platform (pure offline logic) ──────────────────────────────────────
def test_calculator():
    _run("calculator.py")


def test_units():
    _run("units.py")


def test_custom_commands():
    _run("test_custom_commands.py")


# ── Windows-only (construct CommandProcessor) ────────────────────────────────
@windows_only
def test_safety():
    _run("test_safety.py")


@windows_only
def test_capabilities():
    _run("test_capabilities.py")


@windows_only
def test_conversational():
    _run("test_conversational.py")


@windows_only
def test_calc_routing():
    _run("test_calc_routing.py")


@windows_only
def test_knowledge():
    _run("test_knowledge.py")


@windows_only
def test_confirm():
    _run("test_confirm.py")


@windows_only
def test_context():
    _run("test_context.py")
