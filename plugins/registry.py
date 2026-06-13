"""Plugin discovery and loading (scaffold for Phase 4)."""
from __future__ import annotations

from core.shared.logger import get_logger
from core.tools.base_tool import BaseTool
from .base_plugin import BasePlugin

log = get_logger(__name__)


class PluginRegistry:
    def __init__(self) -> None:
        self._plugins: dict[str, BasePlugin] = {}

    async def load(self, plugin: BasePlugin) -> list[BaseTool]:
        await plugin.on_load()
        tools = await plugin.register()
        self._plugins[plugin.manifest.name] = plugin
        log.info("plugin.loaded", name=plugin.manifest.name, tools=len(tools))
        return tools

    async def unload(self, name: str) -> None:
        plugin = self._plugins.pop(name, None)
        if plugin:
            await plugin.on_unload()

    def list(self) -> list[dict]:
        return [p.manifest.model_dump() for p in self._plugins.values()]
