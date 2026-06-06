"""
app_discovery.py - Dynamic Windows app discovery for NirmiqEcho

Finds installed apps by scanning:
  1. Known static APP_MAP (instant lookup)
  2. Windows Registry (HKLM + HKCU uninstall keys)
  3. Start Menu shortcuts (.lnk files)
  4. Common install directories
  5. PATH executables

Uses fuzzy matching (difflib) so "brave browser" still finds "Brave".

Results are cached after first scan for instant subsequent lookups.
"""

import os
import re
import glob
import winreg
import logging
import difflib
from pathlib import Path
from functools import lru_cache

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────
# Static priority map (checked first — exact match, instant)
# ─────────────────────────────────────────────────────────────────────

STATIC_MAP: dict[str, str] = {
    # Browsers
    "chrome":               "chrome",
    "google chrome":        "chrome",
    "firefox":              "firefox",
    "edge":                 "msedge",
    "microsoft edge":       "msedge",
    "brave":                "brave",
    "opera":                "opera",

    # Communication
    "whatsapp":             r"C:\Users\Siddharth\AppData\Local\WhatsApp\WhatsApp.exe",
    "telegram":             "telegram",
    "discord":              "discord",
    "teams":                "teams",
    "microsoft teams":      "teams",
    "zoom":                 "zoom",
    "slack":                "slack",

    # Media
    "spotify":              "spotify",
    "vlc":                  "vlc",
    "media player":         "wmplayer",
    "windows media player": "wmplayer",
    "groove":               "mswindowsmusic:",
    "groove music":         "mswindowsmusic:",
    "photos":               "ms-photos:",
    "netflix":              "https://www.netflix.com",

    # Productivity
    "notepad":              "notepad",
    "notepad++":            r"C:\Program Files\Notepad++\notepad++.exe",
    "word":                 "winword",
    "microsoft word":       "winword",
    "excel":                "excel",
    "powerpoint":           "powerpnt",
    "onenote":              "onenote",
    "outlook":              "outlook",

    # Development
    "vscode":               "code",
    "vs code":              "code",
    "visual studio code":   "code",
    "visual studio":        r"C:\Program Files\Microsoft Visual Studio\2022\Community\Common7\IDE\devenv.exe",
    "pycharm":              "pycharm64",
    "android studio":       "studio64",
    "jupyter":              "jupyter notebook",
    "terminal":             "wt",
    "windows terminal":     "wt",
    "command prompt":       "cmd",
    "cmd":                  "cmd",
    "powershell":           "powershell",
    "git bash":             r"C:\Program Files\Git\git-bash.exe",
    "postman":              "postman",

    # System
    "calculator":           "calc",
    "paint":                "mspaint",
    "task manager":         "taskmgr",
    "file explorer":        "explorer",
    "explorer":             "explorer",
    "settings":             "ms-settings:",
    "control panel":        "control",
    "device manager":       "devmgmt.msc",
    "registry editor":      "regedit",
    "snipping tool":        "snippingtool",

    # Gaming / Launchers
    "steam":                "steam",
    "epic games":           r"C:\Program Files (x86)\Epic Games\Launcher\Portal\Binaries\Win32\EpicGamesLauncher.exe",
    "xbox":                 "xboxapp:",
}

# Common process name fragments → friendly names (for close_app)
PROCESS_ALIASES: dict[str, str] = {
    "chrome":     "chrome.exe",
    "google chrome": "chrome.exe",
    "firefox":    "firefox.exe",
    "edge":       "msedge.exe",
    "brave":      "brave.exe",
    "spotify":    "Spotify.exe",
    "discord":    "Discord.exe",
    "whatsapp":   "WhatsApp.exe",
    "telegram":   "Telegram.exe",
    "zoom":       "Zoom.exe",
    "slack":      "slack.exe",
    "teams":      "Teams.exe",
    "vlc":        "vlc.exe",
    "notepad":    "notepad.exe",
    "notepad++":  "notepad++.exe",
    "vscode":     "Code.exe",
    "vs code":    "Code.exe",
    "visual studio code": "Code.exe",
    "word":       "WINWORD.EXE",
    "excel":      "EXCEL.EXE",
    "powerpoint": "POWERPNT.EXE",
    "pycharm":    "pycharm64.exe",
    "android studio": "studio64.exe",
    "explorer":   "explorer.exe",
    "file explorer": "explorer.exe",
    "terminal":   "WindowsTerminal.exe",
    "steam":      "steam.exe",
    "task manager": "Taskmgr.exe",
}


class AppDiscovery:
    """
    Discovers installed Windows applications dynamically.

    Usage:
        disc = AppDiscovery()
        exe = disc.find("brave browser")   # → "brave"
        exe = disc.find("android studio")  # → "studio64.exe" from registry
    """

    def __init__(self):
        self._cache: dict[str, str] = {}   # name.lower() → executable path
        self._cache_built = False
        self._registry_apps: dict[str, str] = {}
        self._startmenu_apps: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def find(self, name: str) -> str:
        """
        Find an executable for the given app name.
        Returns executable path/name, or "" if not found.
        """
        name = name.strip()
        key = name.lower()

        # 1. Static map (instant, highest priority)
        static = STATIC_MAP.get(key, "")
        if static:
            return static

        # 2. Check our built cache
        if key in self._cache:
            return self._cache[key]

        # 3. Build cache if not done yet
        if not self._cache_built:
            self._build_cache()

        # 4. Exact match in cache
        if key in self._cache:
            return self._cache[key]

        # 5. Fuzzy match
        return self._fuzzy_find(key)

    def find_process(self, name: str) -> str:
        """
        Find the .exe process name for closing an app.
        Returns process name like "chrome.exe" or best guess.
        """
        key = name.lower().strip()

        # Check PROCESS_ALIASES
        if key in PROCESS_ALIASES:
            return PROCESS_ALIASES[key]

        # Try to derive from find()
        exe = self.find(name)
        if exe and exe.endswith(".exe"):
            return os.path.basename(exe)

        # Fuzzy on process aliases
        matches = difflib.get_close_matches(
            key, PROCESS_ALIASES.keys(), n=1, cutoff=0.5
        )
        if matches:
            return PROCESS_ALIASES[matches[0]]

        # Last resort: just append .exe and hope
        return f"{name.lower().split()[0]}.exe"

    def all_app_names(self) -> list[str]:
        """Return all known friendly app names (for hotwords)."""
        if not self._cache_built:
            self._build_cache()
        names = list(STATIC_MAP.keys()) + list(self._cache.keys())
        return sorted(set(names))

    # ------------------------------------------------------------------
    # Cache building
    # ------------------------------------------------------------------

    def _build_cache(self) -> None:
        """Scan registry and Start Menu, populate self._cache."""
        logger.info("AppDiscovery: building app cache...")
        self._scan_registry()
        self._scan_startmenu()
        self._cache_built = True
        logger.info("AppDiscovery: found %d apps total", len(self._cache))

    def _scan_registry(self) -> None:
        """Scan Windows uninstall registry keys for installed apps."""
        reg_paths = [
            (winreg.HKEY_LOCAL_MACHINE,
             r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_LOCAL_MACHINE,
             r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_CURRENT_USER,
             r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        ]

        for hive, path in reg_paths:
            try:
                with winreg.OpenKey(hive, path) as key:
                    count = winreg.QueryInfoKey(key)[0]
                    for i in range(count):
                        try:
                            sub_name = winreg.EnumKey(key, i)
                            with winreg.OpenKey(key, sub_name) as sub:
                                try:
                                    display_name = winreg.QueryValueEx(sub, "DisplayName")[0]
                                    install_loc = self._get_registry_value(
                                        sub, "InstallLocation", "")
                                    exe_str = self._get_registry_value(
                                        sub, "DisplayIcon", "")

                                    if display_name and exe_str:
                                        exe_path = exe_str.split(",")[0].strip('"')
                                        if exe_path.lower().endswith(".exe") and \
                                                os.path.exists(exe_path):
                                            key_name = display_name.lower()
                                            self._cache[key_name] = exe_path
                                            # Also add short name (first word)
                                            short = display_name.split()[0].lower()
                                            if short not in self._cache:
                                                self._cache[short] = exe_path
                                except (FileNotFoundError, OSError):
                                    pass
                        except OSError:
                            continue
            except (FileNotFoundError, PermissionError, OSError):
                continue

    def _scan_startmenu(self) -> None:
        """Scan Start Menu .lnk files for installed apps."""
        start_menu_dirs = [
            Path(os.environ.get("APPDATA", "")) /
                "Microsoft" / "Windows" / "Start Menu" / "Programs",
            Path(os.environ.get("ProgramData", "C:/ProgramData")) /
                "Microsoft" / "Windows" / "Start Menu" / "Programs",
        ]

        for start_dir in start_menu_dirs:
            if not start_dir.exists():
                continue
            for lnk in start_dir.rglob("*.lnk"):
                try:
                    # Use PowerShell to resolve the shortcut target
                    friendly_name = lnk.stem.lower()
                    if friendly_name not in self._cache:
                        # Store the .lnk path — we'll launch it directly
                        self._cache[friendly_name] = str(lnk)
                except Exception:
                    continue

    def _fuzzy_find(self, name: str) -> str:
        """Fuzzy match name against all known app names."""
        all_keys = list(STATIC_MAP.keys()) + list(self._cache.keys())
        matches = difflib.get_close_matches(name, all_keys, n=1, cutoff=0.6)
        if matches:
            best = matches[0]
            result = STATIC_MAP.get(best) or self._cache.get(best, "")
            if result:
                logger.info("AppDiscovery fuzzy: '%s' → '%s' (%s)", name, best, result[:50])
            return result
        return ""

    @staticmethod
    def _get_registry_value(key, name: str, default="") -> str:
        try:
            return winreg.QueryValueEx(key, name)[0]
        except (FileNotFoundError, OSError):
            return default


# Singleton
_discovery = None

def get_discovery() -> AppDiscovery:
    global _discovery
    if _discovery is None:
        _discovery = AppDiscovery()
    return _discovery
