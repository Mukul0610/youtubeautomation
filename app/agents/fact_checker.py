from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field, ValidationError

from app.llm.factory import create_model
from app.models.fact_check import (
    FactCheckedClaim,
    FactCheckResult,
    RecommendedAction,
)
from app.models.research import ClaimStatus, ResearchClaim, ResearchProject, Source


class ClaimAssessment(BaseModel):
    claim: str = Field(..., min_length=1)
    reasoning: str = Field(..., min_length=1)
    supporting_sources: list[str] = Field(default_factory=list)
    contradictory_sources: list[str] = Field(default_factory=list)


class FactCheckAssessment(BaseModel):
    assessments: list[ClaimAssessment] = Field(default_factory=list)


class FactChecker:
    """Evaluate research claims using attached evidence and source metadata."""

    def __init__(self, model: Any | None = None):
        self.model = model

    def check(
        self,
        project: ResearchProject,
        *,
        project_id: str | None = None,
        project_dir: str | Path | None = None,
    ) -> FactCheckResult:
        if project_dir is not None:
            cached = self.load_result(project_dir)
            if cached is not None:
                return cached

        assessments = self._get_assessments(project)
        checked_claims = [
            self._check_claim(claim, project, assessments.get(claim.claim))
            for claim in project.claims
        ]
        result = self._build_result(checked_claims, project_id)
        if project_dir is not None:
            self.persist_result(result, project_dir)
        return result

    def _check_claim(
        self,
        claim: ResearchClaim,
        project: ResearchProject,
        assessment: ClaimAssessment | None,
    ) -> FactCheckedClaim:
        source_urls = self._source_urls(claim, project)
        source_quality = [self.source_quality(url, project) for url in source_urls]
        evidence = claim.evidence.strip().lower()
        numerical_claim = bool(re.search(r"(?:\$|%|\b\d[\d,.]*\b)", claim.claim))
        has_numbers_in_evidence = bool(re.search(r"(?:\$|%|\b\d[\d,.]*\b)", claim.evidence))
        attached_urls = self._attached_source_urls(claim, project)
        assessment_supporting = self._valid_urls(assessment.supporting_sources if assessment else [], attached_urls)
        assessment_contradictory = self._valid_urls(assessment.contradictory_sources if assessment else [], attached_urls)
        contradictory = bool(assessment_contradictory) or any(
            marker in evidence for marker in ("contradict", "conflicting", "disagree")
        )
        unsupported = any(marker in evidence for marker in ("unsupported", "no evidence", "cannot verify"))

        if contradictory:
            status = ClaimStatus.NEEDS_REVIEW
            confidence = 0.35
            action = RecommendedAction.RESEARCH_MORE
            reason = "Attached sources or evidence conflict; the disagreement must be resolved before publication."
        elif unsupported:
            status = ClaimStatus.REJECTED
            confidence = 0.85
            action = RecommendedAction.REMOVE_OR_REWRITE
            reason = "The attached evidence explicitly does not support the claim."
        elif not source_urls:
            status = ClaimStatus.NEEDS_REVIEW
            confidence = 0.2
            action = RecommendedAction.RESEARCH_MORE
            reason = "No source URL is attached, so the claim cannot be verified."
        elif numerical_claim and not has_numbers_in_evidence:
            status = ClaimStatus.NEEDS_REVIEW
            confidence = 0.4
            action = RecommendedAction.RESEARCH_MORE
            reason = "The claim contains a numerical value that is not present in the attached evidence."
        elif min(source_quality, default=0.0) < 0.45:
            status = ClaimStatus.NEEDS_REVIEW
            confidence = 0.5
            action = RecommendedAction.RESEARCH_MORE
            reason = "The attached source is lower quality; corroboration from a primary or authoritative source is needed."
        else:
            status = ClaimStatus.VERIFIED
            confidence = min(0.9, 0.65 + (0.1 * min(len(source_urls), 2)))
            action = RecommendedAction.ACCEPT
            reason = "The claim has attached evidence and at least one sufficiently authoritative source."

        if assessment and assessment.reasoning:
            reason = f"{reason} Model assessment: {assessment.reasoning}"
        supporting = assessment_supporting or source_urls
        contradictory_sources = assessment_contradictory
        return FactCheckedClaim(
            original_claim=claim.claim,
            status=status,
            confidence=confidence,
            reasoning=reason,
            supporting_sources=self._valid_urls(supporting, attached_urls),
            contradictory_sources=self._valid_urls(contradictory_sources, attached_urls),
            recommended_action=action,
        )

    def _get_assessments(self, project: ResearchProject) -> dict[str, ClaimAssessment]:
        if not project.claims:
            return {}
        model = self.model or create_model(agent_name="factcheck")
        prompt = ChatPromptTemplate.from_messages([
            ("system", "Assess claims only against the supplied evidence and source URLs. Do not invent facts, URLs, or evidence. Return structured assessments with reasoning and source URLs copied exactly from the input."),
            ("user", "Research project:\n{project}\nClaims:\n{claims}"),
        ])
        project_text = project.model_dump_json()
        claims_text = json.dumps([claim.model_dump() for claim in project.claims])
        messages = prompt.format_messages(project=project_text, claims=claims_text)
        for attempt in range(2):
            try:
                if hasattr(model, "with_structured_output"):
                    response = model.with_structured_output(FactCheckAssessment).invoke(messages)
                    parsed = response if isinstance(response, FactCheckAssessment) else FactCheckAssessment.model_validate(response)
                else:
                    response = model.invoke(messages)
                    parsed = self._parse_response(response.content)
                return {item.claim: item for item in parsed.assessments}
            except (ValidationError, ValueError, TypeError, json.JSONDecodeError) as exc:
                if attempt == 1:
                    raise ValueError("Fact checker received invalid structured output after retry") from exc
        return {}

    @staticmethod
    def _parse_response(raw: Any) -> FactCheckAssessment:
        if isinstance(raw, dict):
            return FactCheckAssessment.model_validate(raw)
        if not isinstance(raw, str):
            raise ValueError("Fact checker response was not JSON")
        text = raw.strip()
        if text.startswith("```"):
            text = text.strip("`").strip()
            if text.startswith("json"):
                text = text[4:].strip()
        return FactCheckAssessment.model_validate_json(text)

    @staticmethod
    def source_quality(url: str, project: ResearchProject) -> float:
        parsed = urlparse(url)
        host = parsed.netloc.lower().removeprefix("www.")
        source = next((item for item in project.sources if isinstance(item, Source) and item.url == url), None)
        publisher = source.publisher.lower() if source else ""
        title = source.title.lower() if source else ""
        if host.endswith(".gov") or host in {"sec.gov", "investor.gov"}:
            return 1.0
        if any(marker in publisher or marker in title for marker in ("annual report", "regulatory", "filing", "investor", "official")):
            return 0.95
        if host.endswith(".edu") or any(marker in publisher for marker in ("university", "journal", "academic")):
            return 0.85
        if host in {"reuters.com", "apnews.com", "ft.com", "wsj.com", "bloomberg.com"}:
            return 0.75
        if any(marker in host for marker in ("blog", "seo", "wordpress")):
            return 0.25
        return 0.45

    @staticmethod
    def _source_urls(claim: ResearchClaim, project: ResearchProject) -> list[str]:
        urls = [claim.source_url] if claim.source_url else []
        return list(dict.fromkeys(urls))

    @staticmethod
    def _attached_source_urls(claim: ResearchClaim, project: ResearchProject) -> list[str]:
        urls = [claim.source_url] if claim.source_url else []
        urls.extend(
            item.url if isinstance(item, Source) else item
            for item in project.sources
            if isinstance(item, Source) or item.startswith(("http://", "https://"))
        )
        return list(dict.fromkeys(urls))

    @staticmethod
    def _valid_urls(urls: list[str], attached_urls: list[str]) -> list[str]:
        attached = set(attached_urls)
        return [
            url for url in dict.fromkeys(urls)
            if url in attached and url.startswith(("http://", "https://"))
        ]

    @staticmethod
    def _build_result(claims: list[FactCheckedClaim], project_id: str | None) -> FactCheckResult:
        counts = {status: sum(claim.status == status for claim in claims) for status in ClaimStatus}
        if counts[ClaimStatus.REJECTED] == len(claims) and claims:
            overall = ClaimStatus.REJECTED
        elif counts[ClaimStatus.NEEDS_REVIEW] or counts[ClaimStatus.REJECTED]:
            overall = ClaimStatus.NEEDS_REVIEW
        else:
            overall = ClaimStatus.VERIFIED
        return FactCheckResult(
            project_id=project_id,
            total_claims=len(claims),
            verified_claims=counts[ClaimStatus.VERIFIED],
            needs_review_claims=counts[ClaimStatus.NEEDS_REVIEW],
            rejected_claims=counts[ClaimStatus.REJECTED],
            claims=claims,
            overall_status=overall,
            needs_more_research=any(claim.status != ClaimStatus.VERIFIED for claim in claims),
        )

    @staticmethod
    def persist_result(result: FactCheckResult, project_dir: str | Path) -> Path:
        output = Path(project_dir) / "fact_check.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(result.model_dump_json(indent=2), encoding="utf-8")
        return output

    @staticmethod
    def load_result(project_dir: str | Path) -> FactCheckResult | None:
        path = Path(project_dir) / "fact_check.json"
        if not path.exists():
            return None
        try:
            return FactCheckResult.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, ValidationError):
            return None
