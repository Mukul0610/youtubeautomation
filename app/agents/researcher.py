from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from langchain_core.prompts import ChatPromptTemplate
from pydantic import ValidationError

from app.llm.factory import create_model
from app.models.research import (
    ClaimStatus,
    ResearchClaim,
    ResearchProject,
    ResearchQuestion,
    ResearchSection,
    Source,
)
from app.tools.research_tools import build_research_tool


class ResearchAgent:
    """Research agent for topic analysis, claim extraction, and evidence capture."""

    def __init__(self, model: Any | None = None):
        self.model = model or create_model(agent_name="research")
        self.tool = build_research_tool()

    def generate_questions(self, topic: str) -> list[ResearchQuestion]:
        prompt = ChatPromptTemplate.from_messages([
            ("system", "You are a careful financial research assistant. Generate a short list of specific high-value questions to investigate before writing financial content. Prefer primary and authoritative sources and avoid unsupported claims."),
            ("user", "Topic: {topic}\nReturn JSON with a 'questions' array. Each object has: question, rationale."),
        ])
        response = self.model.invoke(prompt.format_messages(topic=topic))
        payload = self._extract_json(response.content)
        items = payload.get("questions", [])
        return [ResearchQuestion.model_validate(item) for item in items]

    def research(self, topic: str) -> ResearchProject:
        questions = self.generate_questions(topic)
        sections = [ResearchSection(title="Core business model"), ResearchSection(title="Revenue mechanism"), ResearchSection(title="Evidence and caveats")]
        search_result = self.tool.search(topic)
        claims = self.extract_claims(topic)
        sources = self._build_sources(search_result.results)
        return ResearchProject(
            topic=topic,
            questions=questions,
            sections=sections,
            claims=claims,
            sources=sources,
        )

    def extract_claims(self, topic: str) -> list[ResearchClaim]:
        prompt = ChatPromptTemplate.from_messages([
            ("system", "Extract factual claims relevant to the topic, always labeling uncertain or unsupported claims as needs_review. Do not invent sources or statistics."),
            ("user", "Topic: {topic}\nReturn JSON with a 'claims' array. Each claim object requires: claim, importance, source_url, source_title, evidence, confidence, status. confidence must be a numeric value from 0.0 to 1.0, never a word."),
        ])
        response = self.model.invoke(prompt.format_messages(topic=topic))
        payload = self._extract_json(response.content)
        claims = []
        for item in payload.get("claims", []):
            try:
                parsed = ResearchClaim.model_validate(item)
            except ValidationError as exc:
                if not isinstance(item, dict) or "claim" not in item or "evidence" not in item:
                    raise ValueError("Research model returned a claim missing required fields") from exc
                repaired = dict(item)
                repaired["confidence"] = 0.0
                repaired["status"] = ClaimStatus.NEEDS_REVIEW
                repaired["evidence"] = f"{repaired['evidence']} Model confidence was invalid; manual verification is required."
                parsed = ResearchClaim.model_validate(repaired)
            if not parsed.source_url and parsed.status == ClaimStatus.VERIFIED:
                parsed.status = ClaimStatus.NEEDS_REVIEW
            claims.append(parsed)
        return claims

    def validate_claims(self, project: ResearchProject) -> ResearchProject:
        validated = []
        for claim in project.claims:
            if not claim.source_url and claim.status == ClaimStatus.VERIFIED:
                claim.status = ClaimStatus.NEEDS_REVIEW
            if claim.confidence < 0.5 and claim.status == ClaimStatus.VERIFIED:
                claim.status = ClaimStatus.NEEDS_REVIEW
            validated.append(claim)
        project.claims = validated
        return project

    def persist_project(self, project: ResearchProject, project_dir: str | Path) -> Path:
        base_dir = Path(project_dir)
        base_dir.mkdir(parents=True, exist_ok=True)
        output = base_dir / "research.json"
        output.write_text(project.model_dump_json(indent=2), encoding="utf-8")
        return output

    def load_project(self, project_dir: str | Path) -> ResearchProject | None:
        file_path = Path(project_dir) / "research.json"
        if not file_path.exists():
            return None
        try:
            return ResearchProject.model_validate_json(file_path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def _build_sources(self, results: list[dict[str, Any]]) -> list[Source]:
        sources: list[Source] = []
        for result in results:
            url = result.get("url")
            if not url:
                continue
            try:
                sources.append(Source.model_validate({
                    "url": url,
                    "title": result.get("title") or "Research source",
                    "publisher": result.get("publisher") or "Unknown publisher",
                    "publication_date": result.get("publication_date"),
                    "accessed_at": result.get("accessed_at"),
                    "relevance": result.get("relevance") or "medium",
                }))
            except Exception:
                continue
        return sources

    @staticmethod
    def _extract_json(raw: Any) -> dict[str, Any]:
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, list):
            text_blocks = [
                block.get("text", "")
                for block in raw
                if isinstance(block, dict) and isinstance(block.get("text"), str)
            ]
            return ResearchAgent._extract_json("\n".join(text_blocks))
        if isinstance(raw, str):
            stripped = raw.strip()
            if stripped.startswith("```") and stripped.endswith("```"):
                stripped = stripped.strip("`").strip()
            if stripped.startswith("json"):
                stripped = stripped[4:].strip()
            try:
                return json.loads(stripped)
            except json.JSONDecodeError:
                return {"questions": [], "claims": []}
        return {"questions": [], "claims": []}
