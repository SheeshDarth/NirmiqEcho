"""
utils.py - Shared utilities for NirmiqEcho

Provides:
- Logging setup
- Hotkey manager wrapper
- System info detection
"""

import logging
import sys
import os
import datetime
import platform
import threading
from pathlib import Path


# ------------------------------------------------------------------
# Logging
# ------------------------------------------------------------------

def setup_logging(level: int = logging.INFO) -> None:
    """Configure root logger to write to console with a clean format."""
    fmt = "%(asctime)s  %(levelname)-8s  %(name)-22s  %(message)s"
    date_fmt = "%H:%M:%S"

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(fmt, date_fmt))

    root = logging.getLogger()
    root.setLevel(level)
    if not root.handlers:
        root.addHandler(handler)

    # Quieten overly verbose third-party libraries
    logging.getLogger("faster_whisper").setLevel(logging.WARNING)
    logging.getLogger("ctranslate2").setLevel(logging.WARNING)
    logging.getLogger("numba").setLevel(logging.WARNING)


# ------------------------------------------------------------------
# System info
# ------------------------------------------------------------------

def get_system_info() -> dict:
    """Return a dictionary of useful system diagnostics."""
    info = {
        "platform": platform.platform(),
        "python": sys.version,
        "cpu_count": os.cpu_count(),
        "cuda_available": False,
    }

    try:
        import torch
        info["cuda_available"] = torch.cuda.is_available()
        if torch.cuda.is_available():
            info["cuda_device"] = torch.cuda.get_device_name(0)
            info["cuda_version"] = torch.version.cuda
    except ImportError:
        pass

    if not info["cuda_available"]:
        try:
            import ctranslate2
            count = ctranslate2.get_cuda_device_count()
            info["cuda_available"] = count > 0
            info["cuda_device_count"] = count
        except Exception:
            pass

    return info


def log_system_info() -> None:
    """Print system info to the console at startup."""
    info = get_system_info()
    logger = logging.getLogger(__name__)
    logger.info("=== NirmiqEcho System Info ===")
    for k, v in info.items():
        logger.info("  %s: %s", k, v)
    logger.info("==============================")


# ------------------------------------------------------------------
# Hotkey manager
# ------------------------------------------------------------------

class HotkeyManager:
    """
    Registers and manages global keyboard hotkeys using the `keyboard` library.
    Hotkeys remain active even when the application window is not focused.

    Note: On Windows, run as Administrator for hotkeys to work across
    elevated windows (Task Manager, IDEs running as admin, etc.).
    """

    def __init__(self):
        self._hotkeys = {}   # hotkey_str -> handler id
        self._lock = threading.Lock()
        self._available = self._check_keyboard()

    @staticmethod
    def _check_keyboard() -> bool:
        try:
            import keyboard  # noqa: F401
            return True
        except ImportError:
            logging.getLogger(__name__).warning(
                "keyboard library not found — hotkeys disabled. "
                "Install with: pip install keyboard"
            )
            return False

    def register(self, hotkey: str, callback) -> bool:
        """Register a global hotkey. Returns True if registration succeeded."""
        if not self._available:
            return False

        import keyboard

        with self._lock:
            if hotkey in self._hotkeys:
                self.unregister(hotkey)
            try:
                handler_id = keyboard.add_hotkey(hotkey, callback, suppress=False)
                self._hotkeys[hotkey] = handler_id
                logging.getLogger(__name__).info("Hotkey registered: %s", hotkey)
                return True
            except Exception as exc:
                logging.getLogger(__name__).warning(
                    "Failed to register hotkey '%s': %s", hotkey, exc
                )
                return False

    def unregister(self, hotkey: str) -> None:
        """Remove a previously registered hotkey."""
        if not self._available:
            return
        import keyboard
        with self._lock:
            if hotkey in self._hotkeys:
                try:
                    keyboard.remove_hotkey(self._hotkeys[hotkey])
                except Exception:
                    pass
                del self._hotkeys[hotkey]

    def unregister_all(self) -> None:
        """Remove all registered hotkeys."""
        for hotkey in list(self._hotkeys.keys()):
            self.unregister(hotkey)

    @property
    def is_available(self) -> bool:
        return self._available
