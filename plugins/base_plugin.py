"""Plugin interface contract (scaffold for Phase 4)."""
from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel

from core.tools.base_tool import BaseTool


class PluginManifest(BaseModel):
    name: str
    version: str
    description: str
    author: str
    tools: list[str] = []
    permissions: list[str] = []


class BasePlugin(ABC):
    manifest: PluginManifest

    @abstractmethod
    async def register(self) -> list[BaseTool]:
        """Return the tools this plugin provides."""

    @abstractmethod
    async def on_load(self) -> None:
        """Called when the plugin is loaded."""

    @abstractmethod
    async def on_unload(self) -> None:
        """Called when the plugin is unloaded."""

    def get_permissions(self) -> list[str]:
        return self.manifest.permissions
