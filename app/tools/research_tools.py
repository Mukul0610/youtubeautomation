from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class ResearchToolResult(BaseModel):
    query: str
    results: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ResearchTool(ABC):
    """Abstract research tool interface."""

    @abstractmethod
    def search(self, query: str) -> ResearchToolResult:
        raise NotImplementedError


class OfflineResearchTool(ResearchTool):
    """Fallback tool for environments without outbound research access."""

    def search(self, query: str) -> ResearchToolResult:
        return ResearchToolResult(
            query=query,
            results=[],
            warnings=["External web research is unavailable in this environment; claims are marked for manual verification."],
        )


class UrlResearchTool(ResearchTool):
    """Minimal direct URL tool. For MVP this is intentionally lightweight."""

    def search(self, query: str) -> ResearchToolResult:
        query_lower = query.strip()
        if not query_lower:
            return ResearchToolResult(query=query, results=[], warnings=["Empty query received."])
        if query_lower.startswith("http://") or query_lower.startswith("https://"):
            return ResearchToolResult(
                query=query,
                results=[{
                    "url": query,
                    "title": "Direct URL source",
                    "publisher": "User provided",
                    "publication_date": None,
                    "accessed_at": datetime.now(timezone.utc).isoformat(),
                    "relevance": "medium",
                }],
                warnings=[],
            )
        return ResearchToolResult(query=query, results=[], warnings=["URL-only mode was not used with a valid URL."])


def build_research_tool() -> ResearchTool:
    # MVP: prefer offline-safe behavior and avoid any hidden network assumption.
    return OfflineResearchTool()
