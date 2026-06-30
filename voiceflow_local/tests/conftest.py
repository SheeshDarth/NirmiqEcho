"""Pytest bootstrap for NirmiqEcho's offline suites.

Puts ``voiceflow_local/`` on ``sys.path`` so any in-process test can import the
app modules (``command_processor``, ``calculator``, ...) by their bare names,
exactly as they resolve when the app runs. The manual / live-dependency scripts
under ``tests/manual/`` are excluded from collection — they launch apps, need
the Whisper models, or need a live Ollama, so they must never run in CI.
"""
import sys
from pathlib import Path

# voiceflow_local/ is the parent of this tests/ directory.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Never auto-collect the side-effecting manual scripts.
collect_ignore_glob = ["manual/*"]
