"""Shared, typed data models for Nirmiq Echo. Single source of truth."""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class EngineMode(str, Enum):
    DICTATION = "dictation"
    ASSISTANT = "assistant"
    RESEARCH = "research"
    DEVELOPER = "developer"
    FOCUS = "focus"


class VoiceState(str, Enum):
    IDLE = "idle"
    LISTENING = "listening"
    VAD_DETECTED = "vad_detected"
    TRANSCRIBING = "transcribing"
    WAKE_DETECTED = "wake_detected"


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    AWAITING_CONFIRMATION = "awaiting_confirmation"


class RiskLevel(str, Enum):
    SAFE = "safe"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class PlanStep(BaseModel):
    step_id: str
    step_number: int
    description: str
    tool_name: str
    tool_args: dict[str, Any] = Field(default_factory=dict)
    status: StepStatus = StepStatus.PENDING
    result: Optional[Any] = None
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    risk_level: RiskLevel = RiskLevel.SAFE


class ExecutionPlan(BaseModel):
    plan_id: str
    raw_intent: str
    steps: list[PlanStep] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_utcnow)
    requires_confirmation: bool = False
    confirmation_message: Optional[str] = None


class ToolResult(BaseModel):
    success: bool
    data: Optional[Any] = None
    error: Optional[str] = None
    verified: bool = False


class WSMessage(BaseModel):
    event: str
    payload: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=_utcnow)


class MemoryEntry(BaseModel):
    memory_id: str
    memory_type: Literal["short", "long", "project", "preference", "workflow"]
    key: str
    value: Any
    tags: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_utcnow)
    accessed_at: Optional[datetime] = None
    access_count: int = 0
