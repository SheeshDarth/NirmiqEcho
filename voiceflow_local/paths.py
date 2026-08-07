r"""paths.py - Where NirmiqEcho keeps its mutable data.

In development the app runs from source and keeps its assets next to the code
(voiceflow_local/assets/) exactly as before. In a frozen PyInstaller build the
install directory is read-only (e.g. Program Files), so all mutable state moves
to %LOCALAPPDATA%\NirmiqEcho. One helper so every write site agrees, and the
frozen app never tries to write inside its own bundle.
"""
import os
import sys
from pathlib import Path

_APP = "NirmiqEcho"


def base_dir() -> Path:
    """Root for mutable data: %LOCALAPPDATA%\\NirmiqEcho when frozen, else source."""
    if getattr(sys, "frozen", False):
        root = os.getenv("LOCALAPPDATA") or os.path.expanduser("~")
        return Path(root) / _APP
    return Path(__file__).resolve().parent


def assets_dir() -> Path:
    """Writable dir for memory.json, command_log.txt, accent_profile.json, etc."""
    d = base_dir() / "assets"
    d.mkdir(parents=True, exist_ok=True)
    return d


if __name__ == "__main__":
    # Self-check: the assets dir must live under the base dir and be creatable.
    a = assets_dir()
    assert a.parent == base_dir(), (a, base_dir())
    assert a.is_dir(), a
    print(f"frozen={getattr(sys, 'frozen', False)}  assets_dir={a}")
