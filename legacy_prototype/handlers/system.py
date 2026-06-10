"""System-level commands — power, lock, screenshot, battery, Wi-Fi."""
from __future__ import annotations

import ctypes
import datetime
import os
import subprocess
from pathlib import Path


def shutdown() -> str:
    subprocess.run("shutdown /s /t 10", shell=True)
    return "Shutting down in 10 seconds. Say cancel shutdown to abort."


def cancel_shutdown() -> str:
    subprocess.run("shutdown /a", shell=True)
    return "Shutdown cancelled."


def restart() -> str:
    subprocess.run("shutdown /r /t 10", shell=True)
    return "Restarting in 10 seconds."


def sleep_pc() -> str:
    subprocess.run("rundll32.exe powrprof.dll,SetSuspendState 0,1,0", shell=True)
    return "Sleeping."


def lock_screen() -> str:
    ctypes.windll.user32.LockWorkStation()
    return "Screen locked."


def screenshot() -> str:
    import pyautogui
    ts       = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    save_dir = Path.home() / "Pictures" / "Screenshots"
    save_dir.mkdir(parents=True, exist_ok=True)
    path = save_dir / f"nirmiq_{ts}.png"
    img  = pyautogui.screenshot()
    img.save(str(path))
    os.startfile(str(save_dir))
    return f"Screenshot saved: {path.name}"


def get_battery() -> str:
    try:
        import psutil
        b = psutil.sensors_battery()
        if b is None:
            return "No battery found — this device may be desktop only."
        status = "charging" if b.power_plugged else "on battery"
        return f"Battery is at {b.percent:.0f}%, {status}."
    except ImportError:
        return "psutil not installed."


def get_wifi() -> str:
    try:
        result = subprocess.run(
            "netsh wlan show interfaces",
            capture_output=True, text=True, shell=True
        )
        lines = result.stdout.splitlines()
        for line in lines:
            if "SSID" in line and "BSSID" not in line:
                ssid = line.split(":", 1)[-1].strip()
                return f"Connected to Wi-Fi: {ssid}"
        return "Not connected to any Wi-Fi network."
    except Exception as e:
        return f"Couldn't check Wi-Fi: {e}"
