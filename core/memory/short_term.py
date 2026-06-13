"""Session-scoped in-memory cache. Lost on restart by design."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from core.shared.types import MemoryEntry


class ShortTermMemory:
    def __init__(self) -> None:
        self._data: dict[str, MemoryEntry] = {}

    def set(self, key: str, value: Any, tags: list[str]) -> MemoryEntry:
        entry = MemoryEntry(
            memory_id=str(uuid.uuid4()),
            memory_type="short",
            key=key,
            value=value,
            tags=tags,
            created_at=datetime.now(timezone.utc),
        )
        self._data[key] = entry
        return entry

    def get(self, key: str) -> Optional[MemoryEntry]:
        entry = self._data.get(key)
        if entry:
            entry.access_count += 1
            entry.accessed_at = datetime.now(timezone.utc)
        return entry

    def list(self) -> list[MemoryEntry]:
        return list(self._data.values())

    def delete(self, key: str) -> bool:
        return self._data.pop(key, None) is not None

    def clear(self) -> None:
        self._data.clear()
