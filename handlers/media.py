"""
Music playback via python-vlc.
Fuzzy-searches ~/Music, Downloads, Desktop for audio files.
Streams from disk — no full-file RAM load.
"""
from __future__ import annotations

import difflib
from functools import lru_cache
from pathlib import Path

try:
    import vlc as _vlc
    _HAS_VLC = True
except ImportError:
    _HAS_VLC = False

_instance = None
_player   = None
_playlist: list[str] = []
_idx: int = 0

MUSIC_DIRS = [
    Path.home() / "Music",
    Path.home() / "Downloads",
    Path.home() / "Desktop",
    Path("D:/Music"),
    Path("E:/Music"),
    Path("D:/Songs"),
]
AUDIO_EXTS = {".mp3", ".flac", ".wav", ".ogg", ".m4a", ".aac", ".wma", ".opus"}


def _player_instance():
    global _instance, _player
    if not _HAS_VLC:
        raise RuntimeError("python-vlc not installed. Run: pip install python-vlc")
    if _instance is None:
        _instance = _vlc.Instance("--no-xlib", "--quiet")
        _player = _instance.media_player_new()
    return _player


@lru_cache(maxsize=1)
def _index() -> list[Path]:
    files = []
    for d in MUSIC_DIRS:
        if d.exists():
            for ext in AUDIO_EXTS:
                files.extend(d.rglob(f"*{ext}"))
    return files


def _fuzzy_find(query: str) -> list[Path]:
    all_f = _index()
    if not all_f:
        return []
    q = query.lower()
    scored = []
    for f in all_f:
        name   = f.stem.lower()
        folder = f.parent.name.lower()
        score  = max(
            difflib.SequenceMatcher(None, q, name).ratio(),
            difflib.SequenceMatcher(None, q, folder).ratio(),
        )
        if q in name or q in folder:
            score += 0.45
        if name.startswith(q):
            score += 0.2
        scored.append((score, f))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [f for s, f in scored if s >= 0.35][:30]


def play_music(query: str) -> str:
    global _playlist, _idx
    matches = _fuzzy_find(query) or (_index.cache_clear() or _fuzzy_find(query))

    if not matches:
        return f"No music found for '{query}'. Make sure files are in ~/Music."

    _playlist = [str(f) for f in matches]
    _idx = 0
    _load(_playlist[0])
    return f"Playing: {Path(_playlist[0]).stem}"


def _load(path: str):
    p = _player_instance()
    media = _instance.media_new(path)
    p.set_media(media)
    p.play()


def pause_music() -> str:
    p = _player_instance()
    p.pause()
    return "Paused." if p.is_playing() == 0 else "Resumed."


def stop_music() -> str:
    p = _player_instance()
    p.stop()
    return "Music stopped."


def next_track() -> str:
    global _idx
    if not _playlist:
        return "No playlist loaded."
    _idx = (_idx + 1) % len(_playlist)
    _load(_playlist[_idx])
    return f"Playing: {Path(_playlist[_idx]).stem}"


def prev_track() -> str:
    global _idx
    if not _playlist:
        return "No playlist loaded."
    _idx = (_idx - 1) % len(_playlist)
    _load(_playlist[_idx])
    return f"Playing: {Path(_playlist[_idx]).stem}"


def set_volume(direction: str, level: int = 10) -> str:
    p = _player_instance()
    cur = p.audio_get_volume()
    if direction == "up":
        new = min(100, cur + 15)
    elif direction == "down":
        new = max(0, cur - 15)
    elif direction == "set":
        new = max(0, min(100, int(level)))
    else:
        new = cur
    p.audio_set_volume(new)
    return f"Volume {new}%."


def toggle_mute() -> str:
    p = _player_instance()
    p.audio_toggle_mute()
    return "Muted." if p.audio_get_mute() else "Unmuted."
