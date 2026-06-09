"""App open / close / minimize — uses subprocess + pygetwindow."""
from __future__ import annotations

import glob
import os
import subprocess
import time

import pygetwindow as gw

_USER = os.environ.get("USERNAME", "")
_APPDATA = os.environ.get("APPDATA", "")
_LOCALAPPDATA = os.environ.get("LOCALAPPDATA", "")

APP_MAP: dict[str, tuple[str, str]] = {
    # name: (window-title-substr, launch-command)
    "whatsapp":             ("WhatsApp",            rf"{_LOCALAPPDATA}\WhatsApp\WhatsApp.exe"),
    "chrome":               ("Google Chrome",        "chrome"),
    "google chrome":        ("Google Chrome",        "chrome"),
    "firefox":              ("Firefox",              "firefox"),
    "edge":                 ("Edge",                 "msedge"),
    "microsoft edge":       ("Edge",                 "msedge"),
    "spotify":              ("Spotify",              rf"{_APPDATA}\Spotify\Spotify.exe"),
    "notepad":              ("Notepad",              "notepad"),
    "notepad++":            ("Notepad++",            "notepad++"),
    "explorer":             ("",                     "explorer"),
    "file explorer":        ("",                     "explorer"),
    "vscode":               ("Visual Studio Code",   "code"),
    "vs code":              ("Visual Studio Code",   "code"),
    "visual studio code":   ("Visual Studio Code",   "code"),
    "terminal":             ("",                     "wt"),
    "windows terminal":     ("",                     "wt"),
    "cmd":                  ("Command Prompt",       "cmd"),
    "command prompt":       ("Command Prompt",       "cmd"),
    "powershell":           ("PowerShell",           "powershell"),
    "calculator":           ("Calculator",           "calc"),
    "task manager":         ("Task Manager",         "taskmgr"),
    "settings":             ("Settings",             "ms-settings:"),
    "paint":                ("Paint",                "mspaint"),
    "word":                 ("Word",                 "winword"),
    "excel":                ("Excel",                "excel"),
    "powerpoint":           ("PowerPoint",           "powerpnt"),
    "outlook":              ("Outlook",              "outlook"),
    "teams":                ("Microsoft Teams",      "ms-teams:"),
    "telegram":             ("Telegram",             rf"{_APPDATA}\Telegram Desktop\Telegram.exe"),
    "discord":              ("Discord",              rf"{_LOCALAPPDATA}\Discord\app-*\Discord.exe"),
    "zoom":                 ("Zoom",                 "Zoom"),
    "vlc":                  ("VLC media player",     "vlc"),
    "photos":               ("Photos",               "ms-photos:"),
    "camera":               ("Camera",               "microsoft.windows.camera:"),
    "paint 3d":             ("Paint 3D",             "ms-paint:"),
    "snipping tool":        ("Snipping Tool",        "snippingtool"),
    "xbox":                 ("Xbox",                 "ms-xbox:"),
    "store":                ("Microsoft Store",      "ms-windows-store:"),
}


def _resolve(name: str) -> tuple[str, str] | None:
    k = name.lower().strip()
    # Exact match first
    if k in APP_MAP:
        return APP_MAP[k]
    # Partial match
    for key, val in APP_MAP.items():
        if key in k or k in key:
            return val
    return None


def _focus(title_substr: str) -> bool:
    if not title_substr:
        return False
    for w in gw.getAllWindows():
        if title_substr.lower() in w.title.lower():
            try:
                w.restore()
                w.activate()
                return True
            except Exception:
                pass
    return False


def open_app(name: str) -> str:
    if not name:
        return "Which app should I open?"

    res = _resolve(name)
    if res:
        title, exe = res
        if _focus(title):
            return f"Switched to {name}."
        try:
            if exe.startswith("ms-") or (":" in exe and "\\" not in exe):
                os.startfile(exe)
            elif "*" in exe:
                matches = glob.glob(exe)
                real_exe = matches[0] if matches else exe.replace("*", "")
                subprocess.Popen(real_exe)
            elif exe.endswith(".exe") or "\\" in exe:
                subprocess.Popen(exe)
            else:
                subprocess.Popen(exe, shell=True)
            return f"Opening {name}."
        except FileNotFoundError:
            subprocess.Popen(name, shell=True)
            return f"Opening {name}."
    else:
        subprocess.Popen(name, shell=True)
        return f"Trying to open {name}."


def close_app(name: str) -> str:
    if not name:
        return "Which app should I close?"
    res = _resolve(name)
    title = res[0] if res else name
    closed = []
    for w in gw.getAllWindows():
        if (title and title.lower() in w.title.lower()) or name.lower() in w.title.lower():
            try:
                w.close()
                closed.append(w.title)
            except Exception:
                pass
    if closed:
        return f"Closed {name}."
    exe_name = (res[1].split("\\")[-1] if res else name + ".exe")
    subprocess.run(f"taskkill /f /im {exe_name}", shell=True, capture_output=True)
    return f"Closed {name}."


def minimize_app(name: str) -> str:
    res = _resolve(name)
    title = res[0] if res else name
    for w in gw.getAllWindows():
        if title.lower() in w.title.lower() or name.lower() in w.title.lower():
            try:
                w.minimize()
                return f"Minimized {name}."
            except Exception:
                pass
    return f"Couldn't find {name} to minimize."
