"""pdf_summarizer — extract PDF text and summarize it with the local LLM."""
from __future__ import annotations

from pathlib import Path

from core.shared.types import RiskLevel, ToolResult
from core.tools.base_tool import BaseTool


class PdfSummarizerTool(BaseTool):
    name = "pdf_summarizer"
    description = "Extract text from a PDF and summarize it with the local model."
    risk_level = RiskLevel.SAFE
    args_hint = "path"

    def __init__(self, router=None):
        self._router = router  # ModelRouter | None

    def validate_args(self, args: dict) -> tuple[bool, str]:
        return (bool(args.get("path")), "path is required")

    async def execute(self, args: dict) -> ToolResult:
        path = Path(str(args["path"])).expanduser()
        if not path.exists():
            return ToolResult(success=False, error="pdf not found")
        text = self._extract(path)
        if not text:
            return ToolResult(success=False, error="could not extract text")
        if not self._router:
            # No LLM wired — return the raw text head as a fallback.
            return ToolResult(success=True, verified=True,
                              data={"text": text[:2000], "summarized": False})
        summary = await self._router.complete(
            "reasoning",
            "Summarize the document in 5 concise bullet points.",
            text[:12000])
        return ToolResult(success=True, verified=True,
                          data={"summary": summary, "summarized": True})

    @staticmethod
    def _extract(path: Path) -> str:
        try:
            import pypdf
            reader = pypdf.PdfReader(str(path))
            return "\n".join((p.extract_text() or "") for p in reader.pages)
        except ImportError:
            try:
                import PyPDF2
                reader = PyPDF2.PdfReader(str(path))
                return "\n".join((p.extract_text() or "") for p in reader.pages)
            except Exception:
                return ""
        except Exception:
            return ""
