"""Unified memory store — SQLite-backed long-term + in-memory short-term."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session, sessionmaker

from core.config.settings import get_settings
from core.shared.logger import get_logger
from core.shared.types import MemoryEntry
from .models import Base, CommandHistoryORM, ExecutionLogORM, MemoryEntryORM
from .short_term import ShortTermMemory

log = get_logger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class MemoryStore:
    """
    The single entry point for all memory. Long-term entries persist to
    SQLite; short-term entries live only for the session.
    """

    def __init__(self, db_path: Optional[Path] = None):
        settings = get_settings()
        self.db_path = Path(db_path or settings.db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._engine = create_engine(f"sqlite:///{self.db_path}", future=True)
        Base.metadata.create_all(self._engine)
        self._Session: sessionmaker[Session] = sessionmaker(
            bind=self._engine, expire_on_commit=False, future=True
        )
        self.short_term = ShortTermMemory()
        log.info("memory.ready", db=str(self.db_path))

    # ── set / get ─────────────────────────────────────────────────────

    def set(self, memory_type: str, key: str, value: Any,
            tags: Optional[list[str]] = None) -> MemoryEntry:
        if memory_type == "short":
            return self.short_term.set(key, value, tags or [])

        with self._Session() as s:
            existing = s.execute(
                select(MemoryEntryORM).where(
                    MemoryEntryORM.memory_type == memory_type,
                    MemoryEntryORM.key == key,
                )
            ).scalar_one_or_none()
            if existing:
                existing.value = json.dumps(value)
                existing.tags = json.dumps(tags or json.loads(existing.tags))
                row = existing
            else:
                row = MemoryEntryORM(
                    id=str(uuid.uuid4()),
                    memory_type=memory_type,
                    key=key,
                    value=json.dumps(value),
                    tags=json.dumps(tags or []),
                    created_at=_now_iso(),
                )
                s.add(row)
            s.commit()
            return self._to_entry(row)

    def get(self, memory_type: str, key: str) -> Optional[MemoryEntry]:
        if memory_type == "short":
            return self.short_term.get(key)
        with self._Session() as s:
            row = s.execute(
                select(MemoryEntryORM).where(
                    MemoryEntryORM.memory_type == memory_type,
                    MemoryEntryORM.key == key,
                )
            ).scalar_one_or_none()
            if not row:
                return None
            row.access_count += 1
            row.accessed_at = _now_iso()
            s.commit()
            return self._to_entry(row)

    def list(self, memory_type: str, limit: int = 50) -> list[MemoryEntry]:
        if memory_type == "short":
            return self.short_term.list()
        with self._Session() as s:
            rows = s.execute(
                select(MemoryEntryORM)
                .where(MemoryEntryORM.memory_type == memory_type)
                .order_by(MemoryEntryORM.created_at.desc())
                .limit(limit)
            ).scalars().all()
            return [self._to_entry(r) for r in rows]

    def delete(self, memory_type: str, key: str) -> bool:
        if memory_type == "short":
            return self.short_term.delete(key)
        with self._Session() as s:
            result = s.execute(
                delete(MemoryEntryORM).where(
                    MemoryEntryORM.memory_type == memory_type,
                    MemoryEntryORM.key == key,
                )
            )
            s.commit()
            return result.rowcount > 0

    def clear_all(self) -> None:
        self.short_term.clear()
        with self._Session() as s:
            s.execute(delete(MemoryEntryORM))
            s.commit()
        log.warning("memory.cleared_all")

    # ── command history / execution logs ──────────────────────────────

    def record_command(self, raw_input: str, intent: Optional[str],
                        plan_id: Optional[str], status: str,
                        duration_ms: Optional[int] = None) -> None:
        with self._Session() as s:
            s.add(CommandHistoryORM(
                id=str(uuid.uuid4()), raw_input=raw_input, intent=intent,
                plan_id=plan_id, status=status, executed_at=_now_iso(),
                duration_ms=duration_ms,
            ))
            s.commit()

    def recent_commands(self, limit: int = 20) -> list[dict]:
        with self._Session() as s:
            rows = s.execute(
                select(CommandHistoryORM)
                .order_by(CommandHistoryORM.executed_at.desc())
                .limit(limit)
            ).scalars().all()
            return [
                {"raw_input": r.raw_input, "status": r.status,
                 "executed_at": r.executed_at}
                for r in rows
            ]

    def record_step(self, plan_id: str, step_number: int, tool_name: str,
                    tool_args: dict, result: Any, status: str) -> None:
        with self._Session() as s:
            s.add(ExecutionLogORM(
                id=str(uuid.uuid4()), plan_id=plan_id, step_number=step_number,
                tool_name=tool_name, tool_args=json.dumps(tool_args),
                result=json.dumps(result, default=str), status=status,
                started_at=_now_iso(), ended_at=_now_iso(),
            ))
            s.commit()

    # ── lifecycle ─────────────────────────────────────────────────────

    def close(self) -> None:
        """Dispose the SQLite engine (releases the file handle on Windows)."""
        self._engine.dispose()

    # ── helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _to_entry(row: MemoryEntryORM) -> MemoryEntry:
        return MemoryEntry(
            memory_id=row.id,
            memory_type=row.memory_type,  # type: ignore[arg-type]
            key=row.key,
            value=json.loads(row.value),
            tags=json.loads(row.tags),
            created_at=datetime.fromisoformat(row.created_at),
            accessed_at=(datetime.fromisoformat(row.accessed_at)
                         if row.accessed_at else None),
            access_count=row.access_count,
        )
