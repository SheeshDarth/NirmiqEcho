"""Type text or press keys into the active window."""
from __future__ import annotations

import time
import pyautogui

pyautogui.PAUSE = 0.08
pyautogui.FAILSAFE = True

KEY_MAP = {
    "enter": "enter",       "return": "enter",
    "space": "space",       "spacebar": "space",
    "backspace": "backspace","delete": "delete",
    "escape": "escape",     "esc": "escape",
    "tab": "tab",
    "up": "up",             "down": "down",
    "left": "left",         "right": "right",
    "home": "home",         "end": "end",
    "page up": "pageup",    "page down": "pagedown",
    "copy": "ctrl+c",       "ctrl c": "ctrl+c",
    "paste": "ctrl+v",      "ctrl v": "ctrl+v",
    "cut": "ctrl+x",        "ctrl x": "ctrl+x",
    "undo": "ctrl+z",       "ctrl z": "ctrl+z",
    "redo": "ctrl+y",       "ctrl y": "ctrl+y",
    "select all": "ctrl+a", "ctrl a": "ctrl+a",
    "save": "ctrl+s",       "ctrl s": "ctrl+s",
    "find": "ctrl+f",       "ctrl f": "ctrl+f",
    "new": "ctrl+n",        "ctrl n": "ctrl+n",
    "close tab": "ctrl+w",
    "alt tab": "alt+tab",
    "alt f4": "alt+f4",
    "windows": "win",       "win": "win",
    "f1": "f1",  "f2": "f2",  "f3": "f3",  "f4": "f4",
    "f5": "f5",  "f6": "f6",  "f11": "f11","f12": "f12",
    "print screen": "printscreen",
    "insert": "insert",
    "num lock": "numlock",
    "caps lock": "capslock",
}


def type_text(text: str) -> str:
    if not text:
        return "What should I type?"
    time.sleep(0.3)
    try:
        import pyperclip
        pyperclip.copy(text)
        pyautogui.hotkey("ctrl", "v")
    except ImportError:
        pyautogui.typewrite(text, interval=0.04)
    return "Done."


def press_key(key: str) -> str:
    if not key:
        return "Which key?"
    k = key.lower().strip()
    mapped = KEY_MAP.get(k, k)
    if "+" in mapped:
        parts = [p.strip() for p in mapped.split("+")]
        pyautogui.hotkey(*parts)
    else:
        pyautogui.press(mapped)
    return f"Pressed {key}."
