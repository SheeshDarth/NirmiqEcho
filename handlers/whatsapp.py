"""
WhatsApp automation — WhatsApp Desktop on Windows.
Strategy: open WhatsApp Desktop → focus → Ctrl+N new chat → search contact
          → select first result → type message → Enter.
"""
from __future__ import annotations

import os
import subprocess
import time

import pyautogui
import pygetwindow as gw

pyautogui.PAUSE = 0.15
pyautogui.FAILSAFE = True

_WA_EXE = os.path.join(os.environ.get("LOCALAPPDATA", ""), "WhatsApp", "WhatsApp.exe")


def _open_and_focus() -> bool:
    for w in gw.getAllWindows():
        if "whatsapp" in w.title.lower():
            w.restore()
            w.activate()
            time.sleep(0.7)
            return True

    exe = _WA_EXE if os.path.exists(_WA_EXE) else "WhatsApp"
    subprocess.Popen(exe, shell=not os.path.exists(_WA_EXE))

    for _ in range(24):
        time.sleep(0.5)
        for w in gw.getAllWindows():
            if "whatsapp" in w.title.lower():
                w.activate()
                time.sleep(1.2)
                return True
    return False


def whatsapp_message(contact: str, message: str) -> str:
    if not contact:
        return "Who should I message on WhatsApp?"
    if not _open_and_focus():
        return "WhatsApp Desktop is not installed or couldn't open."

    # New chat / search
    pyautogui.hotkey("ctrl", "n")
    time.sleep(0.7)
    pyautogui.hotkey("ctrl", "a")
    pyautogui.typewrite(contact, interval=0.05)
    time.sleep(1.3)

    # Select first result
    pyautogui.press("down")
    time.sleep(0.25)
    pyautogui.press("enter")
    time.sleep(0.8)

    if not message:
        return f"Opened chat with {contact}. What would you like to say?"

    # Paste message (handles Unicode better than typewrite)
    try:
        import pyperclip
        pyperclip.copy(message)
        pyautogui.hotkey("ctrl", "v")
    except ImportError:
        pyautogui.typewrite(message, interval=0.04)

    time.sleep(0.2)
    pyautogui.press("enter")
    return f"Message sent to {contact}."


def whatsapp_call(contact: str) -> str:
    if not _open_and_focus():
        return "WhatsApp Desktop couldn't open."
    pyautogui.hotkey("ctrl", "n")
    time.sleep(0.7)
    pyautogui.hotkey("ctrl", "a")
    pyautogui.typewrite(contact, interval=0.05)
    time.sleep(1.3)
    pyautogui.press("down")
    time.sleep(0.25)
    pyautogui.press("enter")
    time.sleep(0.8)
    return f"Opened {contact}'s chat — click the call button to start the call."


def whatsapp_video_call(contact: str) -> str:
    result = whatsapp_call(contact)
    return result.replace("call button", "video call button")
