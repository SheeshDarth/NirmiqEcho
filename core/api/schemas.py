"""Request/response schemas for the REST + WS API."""
from __future__ import annotations

from pydantic import BaseModel

from core.shared.types import EngineMode


class IntentRequest(BaseModel):
    text: str
    mode: EngineMode = EngineMode.ASSISTANT


class ConfirmationRequest(BaseModel):
    plan_id: str
    confirmed: bool


class ModeRequest(BaseModel):
    mode: EngineMode


class StatusResponse(BaseModel):
    mic: bool
    llm: bool
    model_name: str
    tools: int
