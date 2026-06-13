"""Pydantic settings — all configuration funnels through here."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEFAULTS_PATH = Path(__file__).parent / "defaults.yaml"
_DATA_DIR = Path.home() / ".nirmiq-echo"


class VoiceSettings(BaseSettings):
    whisper_model: str = "small.en"
    sample_rate: int = 16000
    silence_timeout_s: float = 1.5
    wake_word: str = "nirmiq"
    wake_confidence: float = 0.5
    noise_suppression: bool = True
    input_device: Optional[str] = None
    # Reuse an existing faster-whisper cache to avoid re-downloading models.
    # Defaults to the proven voiceflow_local models dir if it exists.
    model_cache: Optional[str] = None


class ModelSettings(BaseSettings):
    ollama_endpoint: str = "http://localhost:11434"
    command_model: str = "qwen3.5:4b"
    planning_model: str = "qwen3.5:4b"
    reasoning_model: str = "mistral:7b-instruct-q4_K_M"


class ServerSettings(BaseSettings):
    host: str = "127.0.0.1"
    ws_port: int = 8765
    http_port: int = 8766


class Settings(BaseSettings):
    """Top-level application settings. Env vars use NIRMIQ_ prefix."""

    model_config = SettingsConfigDict(
        env_prefix="NIRMIQ_", env_nested_delimiter="__", extra="ignore"
    )

    data_dir: Path = _DATA_DIR
    db_path: Path = _DATA_DIR / "memory.db"
    notes_dir: Path = Path.home() / "NirmiqNotes"
    log_level: str = "INFO"

    voice: VoiceSettings = Field(default_factory=VoiceSettings)
    models: ModelSettings = Field(default_factory=ModelSettings)
    server: ServerSettings = Field(default_factory=ServerSettings)

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.notes_dir.mkdir(parents=True, exist_ok=True)


def _load_yaml_defaults() -> dict:
    if _DEFAULTS_PATH.exists():
        with open(_DEFAULTS_PATH, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """Return the process-wide Settings singleton (yaml defaults + env overrides)."""
    global _settings
    if _settings is None:
        defaults = _load_yaml_defaults()
        _settings = Settings(**defaults)
        _settings.ensure_dirs()
    return _settings
