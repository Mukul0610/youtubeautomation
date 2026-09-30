from pathlib import Path

import pytest
from pydantic import ValidationError

from app.agents.fact_checker import FactChecker
from app.graph.state import VideoState
from app.graph.workflow import node_fact_check
from app.models.fact_check import FactCheckResult, RecommendedAction
from app.models.research import ClaimStatus, ResearchProject, Source


class FakeModel:
    def __init__(self, payload):
        self.payload = payload
        self.calls = 0

    def invoke(self, messages):
        self.calls += 1
        return type("Response", (), {"content": self.payload})()


def make_project(claim, *, source_url="https://www.sec.gov/filings/report", source_title="Annual Report", publisher="Regulatory filing"):
    sources = [] if not source_url else [{
        "url": source_url,
        "title": source_title,
        "publisher": publisher,
        "relevance": "high",
    }]
    return ResearchProject.model_validate({
        "topic": "How Visa Makes Money Without Lending You Money",
        "claims": [{
            "claim": claim,
            "importance": "high",
            "source_url": source_url,
            "source_title": source_title,
            "evidence": "The annual report supports the stated claim with reported figures.",
            "confidence": 0.8,
            "status": "verified",
        }],
        "sources": sources,
    })


def response_for(claim, *, supporting=None, contradictory=None, reasoning="Evidence was reviewed."):
    return {"assessments": [{
        "claim": claim,
        "reasoning": reasoning,
        "supporting_sources": supporting or [],
        "contradictory_sources": contradictory or [],
    }]}


def test_verified_claim():
    claim = "Visa reports payment network revenue."
    agent = FactChecker(FakeModel(response_for(claim)))
    result = agent.check(make_project(claim))
    assert result.claims[0].status == ClaimStatus.VERIFIED
    assert result.overall_status == ClaimStatus.VERIFIED


def test_unsupported_claim_is_rejected():
    claim = "Visa owns every bank in the world."
    project = make_project(claim)
    project.claims[0].evidence = "No evidence supports this unsupported claim."
    result = FactChecker(FakeModel(response_for(claim))).check(project)
    assert result.claims[0].status == ClaimStatus.REJECTED
    assert result.claims[0].recommended_action == RecommendedAction.REMOVE_OR_REWRITE


def test_contradictory_evidence_needs_review():
    claim = "Visa has never changed its pricing."
    project = make_project(claim)
    project.sources.append(Source(
        url="https://example.com/contradiction",
        title="Contradictory report",
        publisher="Example publication",
    ))
    result = FactChecker(FakeModel(response_for(claim, contradictory=["https://example.com/contradiction"]))).check(project)
    assert result.claims[0].status == ClaimStatus.NEEDS_REVIEW
    assert result.claims[0].contradictory_sources == ["https://example.com/contradiction"]


def test_missing_source_needs_review():
    claim = "Visa operates a global payment network."
    result = FactChecker(FakeModel(response_for(claim))).check(make_project(claim, source_url=""))
    assert result.claims[0].status == ClaimStatus.NEEDS_REVIEW
    assert result.needs_more_research is True


def test_low_quality_source_needs_review():
    claim = "Visa earns payment processing revenue."
    result = FactChecker(FakeModel(response_for(claim))).check(make_project(
        claim,
        source_url="https://random-blog.example/visa",
        source_title="Visa facts",
        publisher="Random blog",
    ))
    assert result.claims[0].status == ClaimStatus.NEEDS_REVIEW


def test_multiple_supporting_sources_are_preserved():
    claim = "Visa reports payment network revenue."
    sources = ["https://www.sec.gov/filings/report", "https://investor.visa.com/annual-report"]
    project = make_project(claim)
    project.sources.append(Source(
        url=sources[1],
        title="Annual Report",
        publisher="Official investor relations",
        relevance="high",
    ))
    result = FactChecker(FakeModel(response_for(claim, supporting=sources))).check(project)
    assert result.claims[0].supporting_sources == sources


def test_conflicting_sources_are_not_arbitrarily_selected():
    claim = "Visa's fee revenue increased last year."
    project = make_project(claim)
    project.sources.append(Source(
        url="https://example.com/old-report",
        title="Older report",
        publisher="Example publication",
    ))
    result = FactChecker(FakeModel(response_for(
        claim,
        contradictory=["https://example.com/old-report"],
        reasoning="The current filing and older report disagree.",
    ))).check(project)
    assert result.claims[0].status == ClaimStatus.NEEDS_REVIEW
    assert "disagreement" in result.claims[0].reasoning


def test_numerical_claim_without_matching_evidence_needs_review():
    claim = "Visa processed 99% of all global payments."
    project = make_project(claim)
    project.claims[0].evidence = "The report describes the payment network but gives no percentage."
    result = FactChecker(FakeModel(response_for(claim))).check(project)
    assert result.claims[0].status == ClaimStatus.NEEDS_REVIEW


def test_fact_check_result_validation_rejects_inconsistent_counts():
    with pytest.raises(ValidationError):
        FactCheckResult.model_validate({
            "total_claims": 1,
            "verified_claims": 1,
            "needs_review_claims": 0,
            "rejected_claims": 0,
            "claims": [],
            "overall_status": "verified",
            "needs_more_research": False,
        })


def test_cached_fact_check_json_avoids_llm_call(tmp_path):
    claim = "Visa reports payment network revenue."
    model = FakeModel(response_for(claim))
    agent = FactChecker(model)
    project = make_project(claim)
    first = agent.check(project, project_id="visa", project_dir=tmp_path)
    model.calls = 0
    second = agent.check(project, project_id="visa", project_dir=tmp_path)
    assert (tmp_path / "fact_check.json").exists()
    assert first.model_dump() == second.model_dump()
    assert model.calls == 0


def test_mocked_llm_response_is_used_and_persisted(tmp_path):
    claim = "Visa reports payment network revenue."
    model = FakeModel(response_for(claim, reasoning="Mocked structured assessment."))
    result = FactChecker(model).check(make_project(claim), project_dir=tmp_path)
    assert model.calls == 1
    assert "Mocked structured assessment." in result.claims[0].reasoning
    assert Path(tmp_path / "fact_check.json").exists()


def test_langgraph_fact_check_updates_state(monkeypatch, tmp_path):
    claim = "Visa reports payment network revenue."
    project = make_project(claim)
    fake_result = FactChecker(FakeModel(response_for(claim))).check(project)

    class StubChecker:
        def check(self, project, *, project_id, project_dir):
            assert project.topic.startswith("How Visa")
            return fake_result

    monkeypatch.setattr("app.graph.workflow.FactChecker", StubChecker)
    monkeypatch.chdir(tmp_path)
    state = VideoState(project_id="visa", topic=project.topic, research=project)
    updated = node_fact_check(state)
    assert updated["fact_check"] == fake_result
    assert updated["errors"] == []
