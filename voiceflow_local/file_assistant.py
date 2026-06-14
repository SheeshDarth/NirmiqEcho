"""
file_assistant.py - Voice-driven file system access for NirmiqEcho

Capabilities:
  find_file(query)         — fuzzy search across user folders, returns best match
  open_file(query)         — find + os.startfile (opens with default app)
  open_folder(name)        — open a named folder in Explorer
  list_folder(path)        — return file count / names (for TTS)
  move_file(src, dst)      — shutil.move
  delete_file(path)        — send to Recycle Bin via send2trash

Search scope (ordered by priority):
  Desktop → Documents → Downloads → Pictures → Music → Videos → OneDrive

Design:
  - No background scanning — all searches are on-demand
  - Fuzzy matching via difflib (no external dependencies)
  - send2trash for safe deletion (files go to Recycle Bin, not permanent delete)
  - Memory usage: essentially zero between calls
"""

import os
import shutil
import logging
import difflib
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────
# Search root directories (ordered by priority)
# ─────────────────────────────────────────────────────────────────────

def _get_search_roots() -> list[Path]:
    """Return user's main folders in priority order."""
    home = Path.home()
    candidates = [
        home / "Desktop",
        home / "Documents",
        home / "Downloads",
        home / "Pictures",
        home / "Music",
        home / "Videos",
        home / "OneDrive",
        home / "OneDrive" / "Desktop",
        home / "OneDrive" / "Documents",
    ]
    return [p for p in candidates if p.exists()]


# Named folder shortcuts (voice → path)
NAMED_FOLDERS: dict[str, str] = {
    "desktop":      str(Path.home() / "Desktop"),
    "documents":    str(Path.home() / "Documents"),
    "downloads":    str(Path.home() / "Downloads"),
    "pictures":     str(Path.home() / "Pictures"),
    "photos":       str(Path.home() / "Pictures"),
    "music":        str(Path.home() / "Music"),
    "videos":       str(Path.home() / "Videos"),
    "movies":       str(Path.home() / "Videos"),
    "onedrive":     str(Path.home() / "OneDrive"),
    "my documents": str(Path.home() / "Documents"),
    "my downloads": str(Path.home() / "Downloads"),
    "my pictures":  str(Path.home() / "Pictures"),
    "my music":     str(Path.home() / "Music"),
    "my videos":    str(Path.home() / "Videos"),
    "c drive":      "C:\\",
    "temp":         str(Path(os.environ.get("TEMP", "C:/Temp"))),
}


# ─────────────────────────────────────────────────────────────────────
# FileAssistant
# ─────────────────────────────────────────────────────────────────────

class FileAssistant:
    """
    Voice-friendly file system operations.

    All methods are safe to call from a background thread.
    Heavy operations (find_file) are on-demand — no background scanning.
    """

    # ── Find ──────────────────────────────────────────────────────────

    def find_file(
        self,
        query: str,
        search_roots: Optional[list[Path]] = None,
        max_depth: int = 4,
        cutoff: float = 0.45,
    ) -> Optional[Path]:
        """
        Fuzzy-search for a file matching `query` across user folders.

        Returns the best-matching Path or None.

        Priority:
          1. Exact filename match (stem)
          2. Exact filename match (with extension stripped from query)
          3. Fuzzy stem match (difflib ≥ cutoff)
          4. Fuzzy full-name match
        """
        query_lower = query.lower().strip()
        # Strip common extension if user said "open resume.pdf"
        query_stem = Path(query_lower).stem

        roots = search_roots or _get_search_roots()

        candidates: list[Path] = []
        for root in roots:
            try:
                for p in root.rglob("*"):
                    if p.is_file():
                        candidates.append(p)
                    # Respect max_depth to avoid runaway scans
                    if len(p.parts) - len(root.parts) > max_depth:
                        continue
            except (PermissionError, OSError):
                continue

        if not candidates:
            logger.info("FileAssistant.find_file: no files found in search roots")
            return None

        # Build lookup tables
        stems = [p.stem.lower() for p in candidates]
        names = [p.name.lower() for p in candidates]

        # 1. Exact stem match
        if query_stem in stems:
            idx = stems.index(query_stem)
            logger.info("FileAssistant.find_file: exact stem match: %s", candidates[idx])
            return candidates[idx]

        # 2. Exact full-name match
        if query_lower in names:
            idx = names.index(query_lower)
            logger.info("FileAssistant.find_file: exact name match: %s", candidates[idx])
            return candidates[idx]

        # 3. Fuzzy stem match
        matches = difflib.get_close_matches(query_stem, stems, n=1, cutoff=cutoff)
        if matches:
            idx = stems.index(matches[0])
            logger.info("FileAssistant.find_file: fuzzy stem '%s' → %s",
                        matches[0], candidates[idx])
            return candidates[idx]

        # 4. Fuzzy name match
        matches = difflib.get_close_matches(query_lower, names, n=1, cutoff=cutoff)
        if matches:
            idx = names.index(matches[0])
            logger.info("FileAssistant.find_file: fuzzy name '%s' → %s",
                        matches[0], candidates[idx])
            return candidates[idx]

        # 5. Substring match (query appears in stem)
        for i, stem in enumerate(stems):
            if query_stem in stem or stem in query_stem:
                logger.info("FileAssistant.find_file: substring match: %s", candidates[i])
                return candidates[i]

        logger.info("FileAssistant.find_file: no match for %r", query)
        return None

    def find_files(
        self,
        query: str,
        n: int = 5,
        cutoff: float = 0.40,
    ) -> list[Path]:
        """Return up to n matching files (for TTS 'I found 3 matches...')."""
        query_lower = query.lower().strip()
        query_stem = Path(query_lower).stem

        roots = _get_search_roots()
        candidates: list[Path] = []
        for root in roots:
            try:
                for p in root.rglob("*"):
                    if p.is_file():
                        candidates.append(p)
            except (PermissionError, OSError):
                continue

        if not candidates:
            return []

        stems = [p.stem.lower() for p in candidates]
        matches = difflib.get_close_matches(query_stem, stems, n=n, cutoff=cutoff)
        result = []
        seen: set[int] = set()
        for m in matches:
            idx = stems.index(m)
            if idx not in seen:
                result.append(candidates[idx])
                seen.add(idx)
        return result

    # ── Open ──────────────────────────────────────────────────────────

    def open_file(self, query: str) -> tuple[bool, str]:
        """
        Find and open a file with its default application.

        Returns (success: bool, message: str)
        """
        match = self.find_file(query)
        if not match:
            msg = f"I couldn't find a file matching '{query}'."
            logger.info("FileAssistant.open_file: not found: %r", query)
            return False, msg

        try:
            os.startfile(str(match))
            msg = f"Opening {match.name}"
            logger.info("FileAssistant.open_file: %s", match)
            return True, msg
        except Exception as exc:
            msg = f"Failed to open {match.name}: {exc}"
            logger.warning("FileAssistant.open_file error: %s", exc)
            return False, msg

    def open_folder(self, name: str) -> tuple[bool, str]:
        """
        Open a named folder in Windows Explorer.

        Supports aliases like 'documents', 'downloads', 'desktop', etc.
        Also accepts an absolute path directly.
        """
        key = name.lower().strip()

        # Named shortcut
        if key in NAMED_FOLDERS:
            path = NAMED_FOLDERS[key]
        elif os.path.isdir(name):
            path = name
        else:
            # Fuzzy match against named folders
            matches = difflib.get_close_matches(key, NAMED_FOLDERS.keys(), n=1, cutoff=0.5)
            if matches:
                path = NAMED_FOLDERS[matches[0]]
            else:
                return False, f"I don't know where '{name}' is."

        try:
            import subprocess
            subprocess.Popen(["explorer", path],
                             creationflags=subprocess.CREATE_NO_WINDOW)
            folder_label = Path(path).name or path
            msg = f"Opening {folder_label}"
            logger.info("FileAssistant.open_folder: %s", path)
            return True, msg
        except Exception as exc:
            msg = f"Failed to open folder: {exc}"
            logger.warning("FileAssistant.open_folder error: %s", exc)
            return False, msg

    def list_folder(self, name: str) -> tuple[bool, str]:
        """
        List files in a named folder — returns a spoken summary string.
        E.g. "Your Downloads folder has 12 files."
        """
        key = name.lower().strip()
        path_str = NAMED_FOLDERS.get(key, "")

        if not path_str:
            matches = difflib.get_close_matches(key, NAMED_FOLDERS.keys(), n=1, cutoff=0.5)
            if matches:
                path_str = NAMED_FOLDERS[matches[0]]

        if not path_str or not os.path.isdir(path_str):
            return False, f"I couldn't find the folder '{name}'."

        try:
            entries = list(Path(path_str).iterdir())
            files = [e for e in entries if e.is_file()]
            folders = [e for e in entries if e.is_dir()]
            folder_label = Path(path_str).name

            msg = (
                f"Your {folder_label} folder has "
                f"{len(files)} file{'s' if len(files) != 1 else ''}"
                f" and {len(folders)} subfolder{'s' if len(folders) != 1 else ''}."
            )
            logger.info("FileAssistant.list_folder: %s → %d files", path_str, len(files))
            return True, msg
        except Exception as exc:
            return False, f"Couldn't list folder: {exc}"

    # ── Move ──────────────────────────────────────────────────────────

    def move_file(self, src_query: str, dst_name: str) -> tuple[bool, str]:
        """
        Find a file matching src_query and move it to dst_name folder.

        dst_name can be a named folder alias or an absolute path.
        """
        src = self.find_file(src_query)
        if not src:
            return False, f"I couldn't find '{src_query}'."

        # Resolve destination
        dst_key = dst_name.lower().strip()
        dst_dir = NAMED_FOLDERS.get(dst_key, "")
        if not dst_dir:
            if os.path.isdir(dst_name):
                dst_dir = dst_name
            else:
                return False, f"I don't know where '{dst_name}' is."

        try:
            dest_path = shutil.move(str(src), dst_dir)
            msg = f"Moved {src.name} to {Path(dst_dir).name}."
            logger.info("FileAssistant.move_file: %s → %s", src, dest_path)
            return True, msg
        except Exception as exc:
            msg = f"Couldn't move the file: {exc}"
            logger.warning("FileAssistant.move_file error: %s", exc)
            return False, msg

    # ── Delete ────────────────────────────────────────────────────────

    def delete_file(self, query: str) -> tuple[bool, str, Optional[Path]]:
        """
        Find a file and move it to the Recycle Bin (safe delete).

        Returns (success, message, path_or_None).
        Callers should ask for confirmation BEFORE calling this.
        """
        match = self.find_file(query)
        if not match:
            return False, f"I couldn't find '{query}'.", None

        try:
            import send2trash
            send2trash.send2trash(str(match))
            msg = f"Moved {match.name} to the Recycle Bin."
            logger.info("FileAssistant.delete_file: %s", match)
            return True, msg, match
        except ImportError:
            # Fallback: os.remove (permanent — warn user)
            try:
                os.remove(str(match))
                msg = f"Permanently deleted {match.name}. (Install send2trash for safer deletes.)"
                logger.warning("FileAssistant.delete_file: permanent delete (send2trash missing): %s", match)
                return True, msg, match
            except Exception as exc:
                return False, f"Couldn't delete: {exc}", None
        except Exception as exc:
            return False, f"Couldn't delete: {exc}", None


# ─────────────────────────────────────────────────────────────────────
# Singleton
# ─────────────────────────────────────────────────────────────────────

_fa: Optional[FileAssistant] = None

def get_file_assistant() -> FileAssistant:
    global _fa
    if _fa is None:
        _fa = FileAssistant()
    return _fa


# ─────────────────────────────────────────────────────────────────────
# Self-test
# ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(message)s")
    fa = FileAssistant()

    print("Test: open_folder('downloads')")
    ok, msg = fa.open_folder("downloads")
    print(f"  {'OK' if ok else 'FAIL'}: {msg}")

    print("Test: list_folder('documents')")
    ok, msg = fa.list_folder("documents")
    print(f"  {'OK' if ok else 'FAIL'}: {msg}")

    print("Test: find_file('readme')")
    result = fa.find_file("readme")
    print(f"  Result: {result}")
