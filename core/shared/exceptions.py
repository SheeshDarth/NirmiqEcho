"""Custom exception hierarchy for Nirmiq Echo."""
from __future__ import annotations


class NirmiqError(Exception):
    """Base class for all Nirmiq Echo errors."""


class ConfigError(NirmiqError):
    """Invalid or missing configuration."""


class MemoryError(NirmiqError):
    """Memory store failure."""


class ToolError(NirmiqError):
    """A tool failed in a way that is not a normal ToolResult(success=False)."""


class ToolNotFoundError(ToolError):
    """Requested tool is not registered."""


class ValidationError(ToolError):
    """Tool argument validation failed."""


class PlanningError(NirmiqError):
    """The planner could not produce a valid plan."""


class ModelError(NirmiqError):
    """LLM backend failure (e.g. Ollama unreachable)."""


class VoiceError(NirmiqError):
    """Audio capture or transcription failure."""
