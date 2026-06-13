"""Browser tools: open_url, search_web."""
from __future__ import annotations

import webbrowser
from urllib.parse import quote_plus, urlparse

from core.shared.types import RiskLevel, ToolResult
from core.tools.base_tool import BaseTool


class OpenUrlTool(BaseTool):
    name = "open_url"
    description = "Open a URL in the default browser."
    risk_level = RiskLevel.SAFE
    args_hint = "url"

    def validate_args(self, args: dict) -> tuple[bool, str]:
        return (bool(args.get("url")), "url is required")

    async def execute(self, args: dict) -> ToolResult:
        url = str(args["url"]).strip()
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        if not urlparse(url).netloc:
            return ToolResult(success=False, error="invalid url")
        webbrowser.open(url)
        return ToolResult(success=True, data={"opened": url}, verified=True)


class SearchWebTool(BaseTool):
    name = "search_web"
    description = "Open a web search for the given query in the default browser."
    risk_level = RiskLevel.SAFE
    args_hint = "query"

    def validate_args(self, args: dict) -> tuple[bool, str]:
        return (bool(args.get("query")), "query is required")

    async def execute(self, args: dict) -> ToolResult:
        q = str(args["query"]).strip()
        url = f"https://www.google.com/search?q={quote_plus(q)}"
        webbrowser.open(url)
        return ToolResult(success=True, data={"searched": q}, verified=True)
