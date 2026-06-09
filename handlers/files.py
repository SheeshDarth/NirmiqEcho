"""File search — walks common user directories and opens with the default app."""
from __future__ import annotations

import difflib
import os
import subprocess
from pathlib import Path

SEARCH_ROOTS = [
    Path.home() / "Desktop",
    Path.home() / "Documents",
    Path.home() / "Downloads",
    Path.home() / "Pictures",
    Path.home() / "Videos",
    Path.home() / "Music",
    Path.home(),
]

FOLDER_MAP = {
    "desktop":   Path.home() / "Desktop",
    "documents": Path.home() / "Documents",
    "downloads": Path.home() / "Downloads",
    "pictures":  Path.home() / "Pictures",
    "photos":    Path.home() / "Pictures",
    "videos":    Path.home() / "Videos",
    "music":     Path.home() / "Music",
}

_MAX_DEPTH = 4


def _walk(root: Path, depth=0):
    if depth > _MAX_DEPTH:
        return
    try:
        for e in root.iterdir():
            yield e
            if e.is_dir():
                yield from _walk(e, depth + 1)
    except PermissionError:
        pass


def _score(query: str, path: Path) -> float:
    q = query.lower()
    name = path.stem.lower()
    s = difflib.SequenceMatcher(None, q, name).ratio()
    if q in name:
        s += 0.5
    if name.startswith(q):
        s += 0.3
    return s


def search_file(query: str, location: str = "") -> str:
    if not query:
        return "What file should I look for?"

    roots = SEARCH_ROOTS
    if location:
        loc = FOLDER_MAP.get(location.lower().strip())
        if loc:
            roots = [loc]

    best: list[tuple[float, Path]] = []
    for root in roots:
        if not root.exists():
            continue
        for p in _walk(root):
            sc = _score(query, p)
            if sc >= 0.4:
                best.append((sc, p))

    if not best:
        return f"No file found matching '{query}'."

    best.sort(key=lambda x: x[0], reverse=True)
    top = best[0][1]
    os.startfile(str(top))
    return f"Found and opened: {top.name}"


def open_file(filename: str) -> str:
    return search_file(filename)


def open_folder(folder: str) -> str:
    key  = folder.lower().strip()
    path = FOLDER_MAP.get(key, Path.home())
    subprocess.Popen(f'explorer "{path}"', shell=True)
    return f"Opening {folder} folder."
