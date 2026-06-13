"""SQLAlchemy ORM models for all persistent memory."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Base(DeclarativeBase):
    pass


class MemoryEntryORM(Base):
    __tablename__ = "memory_entries"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    memory_type: Mapped[str] = mapped_column(String, nullable=False)
    key: Mapped[str] = mapped_column(String, nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)         # JSON
    tags: Mapped[str] = mapped_column(Text, default="[]")            # JSON list
    created_at: Mapped[str] = mapped_column(String, default=_now_iso)
    accessed_at: Mapped[str | None] = mapped_column(String, nullable=True)
    access_count: Mapped[int] = mapped_column(Integer, default=0)


class CommandHistoryORM(Base):
    __tablename__ = "command_history"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    raw_input: Mapped[str] = mapped_column(Text, nullable=False)
    intent: Mapped[str | None] = mapped_column(Text, nullable=True)
    plan_id: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False)
    executed_at: Mapped[str] = mapped_column(String, default=_now_iso)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)


class ExecutionLogORM(Base):
    __tablename__ = "execution_logs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    plan_id: Mapped[str] = mapped_column(String, nullable=False)
    step_number: Mapped[int] = mapped_column(Integer, nullable=False)
    tool_name: Mapped[str] = mapped_column(String, nullable=False)
    tool_args: Mapped[str] = mapped_column(Text, nullable=False)     # JSON
    result: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON
    status: Mapped[str] = mapped_column(String, nullable=False)
    started_at: Mapped[str] = mapped_column(String, default=_now_iso)
    ended_at: Mapped[str | None] = mapped_column(String, nullable=True)
