from pathlib import Path

import pytest
from pydantic import ValidationError

from app.agents.researcher import ResearchAgent
from app.graph.state import VideoState
from app.models.research import (
    ClaimStatus,
    ResearchClaim,
    ResearchProject,
    ResearchQuestion,
    ResearchSection,
    Source,
)


class FakeModel:
    def __init__(self, payload):
        self.payload = payload

    def invoke(self, messages):
        return type("Response", (), {"content": self.payload})()


def test_research_project_validation_allows_legacy_and_structured_forms():
    project = ResearchProject.model_validate({
        "topic": "How Visa makes money",
        "key_questions": ["How does Visa make money?"],
        "sections": ["Business model"],
        "claims": [{
            "claim": "Visa earns fee revenue.",
            "importance": "high",
            "source_url": "https://example.com/payments",
            "source_title": "Visa Investor Overview",
            "evidence": "Visa reports transaction fees and processing revenue.",
            "confidence": 0.9,
            "status": "verified",
        }],
        "sources": ["https://example.com/payments"],
    })
    assert project.topic == "How Visa makes money"
    assert len(project.questions) == 1
    assert project.claims[0].status == ClaimStatus.VERIFIED


def test_research_claim_validation_rejects_invalid_status_and_url():
    with pytest.raises(ValidationError):
        ResearchClaim.model_validate({
            "claim": "bad claim",
            "importance": "high",
            "source_url": "not-a-url",
            "source_title": "title",
            "evidence": "evidence",
            "confidence": 0.8,
            "status": "unknown",
        })

    claim = ResearchClaim.model_validate({
        "claim": "Visa earns fee revenue.",
        "importance": "medium",
        "source_url": "https://example.com/source",
        "source_title": "Visa annual report",
        "evidence": "Evidence is present.",
        "confidence": 0.74,
        "status": "needs_review",
    })
    assert claim.status == ClaimStatus.NEEDS_REVIEW


def test_source_validation_accepts_minimal_data():
    source = Source.model_validate({
        "url": "https://company.example/investor-relations",
        "title": "Investor Relations",
        "publisher": "Company",
        "relevance": "high",
    })
    assert source.publisher == "Company"
    assert source.relevance == "high"


def test_research_agent_generates_questions():
    fake_model = FakeModel(
        '{"questions": [{"question": "How does Visa generate revenue?", "rationale": "Core business model"}, {"question": "What do payment networks charge for?", "rationale": "Revenue drivers"}]}'
    )
    agent = ResearchAgent(model=fake_model)
    questions = agent.generate_questions("How Visa makes money")
    assert len(questions) == 2
    assert isinstance(questions[0], ResearchQuestion)
    assert "Visa" in questions[0].question


def test_research_agent_parses_langchain_text_blocks():
    fake_model = FakeModel(
        [{"type": "text", "text": '{"questions": [{"question": "How does Visa generate revenue?", "rationale": "Revenue model"}]}'}]
    )
    agent = ResearchAgent(model=fake_model)
    questions = agent.generate_questions("How Visa makes money")
    assert len(questions) == 1


def test_research_agent_extracts_claims_and_marks_missing_evidence():
    fake_model = FakeModel(
        '{"claims": [{"claim": "Visa earns processing revenue from card transactions.", "importance": "high", "source_url": "", "source_title": "", "evidence": "No external source was available during this offline run.", "confidence": 0.5, "status": "needs_review"}]}'
    )
    agent = ResearchAgent(model=fake_model)
    claims = agent.extract_claims("How Visa makes money")
    assert claims[0].status == ClaimStatus.NEEDS_REVIEW
    assert claims[0].confidence < 1.0


def test_research_agent_does_not_translate_text_confidence():
    fake_model = FakeModel(
        '{"claims": [{"claim": "Visa earns processing revenue.", "importance": "high", "source_url": "https://example.com/source", "source_title": "Report", "evidence": "The report describes processing revenue.", "confidence": "high", "status": "verified"}]}'
    )
    agent = ResearchAgent(model=fake_model)
    claims = agent.extract_claims("How Visa makes money")
    assert claims[0].confidence == 0.0
    assert claims[0].status == ClaimStatus.NEEDS_REVIEW


def test_research_agent_validates_claims_against_sources():
    fake_model = FakeModel(
        '{"claims": [{"claim": "Visa earns processing revenue from card transactions.", "importance": "high", "source_url": "https://example.com/payments", "source_title": "Visa overview", "evidence": "Processing revenue is described.", "confidence": 0.85, "status": "verified"}]}'
    )
    agent = ResearchAgent(model=fake_model)
    project = ResearchProject.model_validate({
        "topic": "How Visa makes money",
        "questions": [{"question": "How does Visa make money?"}],
        "sections": [ResearchSection(title="Business model")],
        "claims": [{
            "claim": "Visa earns processing revenue from card transactions.",
            "importance": "high",
            "source_url": "https://example.com/payments",
            "source_title": "Visa overview",
            "evidence": "Processing revenue is described.",
            "confidence": 0.85,
            "status": "verified",
        }],
        "sources": [{
            "url": "https://example.com/payments",
            "title": "Visa overview",
            "publisher": "Example publisher",
            "relevance": "high",
        }],
    })
    validated = agent.validate_claims(project)
    assert len(validated.claims) == 1
    assert validated.claims[0].status in {ClaimStatus.VERIFIED, ClaimStatus.NEEDS_REVIEW}


def test_research_state_update():
    state = VideoState(project_id="proj-123", topic="How Visa makes money")
    state["research"] = ResearchProject.model_validate({
        "topic": "How Visa makes money",
        "questions": [{"question": "How does Visa make money?"}],
        "sections": ["Business model"],
        "claims": [],
        "sources": [],
    })
    assert state["research"].topic == "How Visa makes money"


def test_research_json_persistence(tmp_path):
    project = ResearchProject.model_validate({
        "topic": "How Visa makes money",
        "questions": [{"question": "How does Visa make money?"}],
        "sections": ["Business model"],
        "claims": [{
            "claim": "Visa earns fee revenue.",
            "importance": "high",
            "source_url": "https://example.com/source",
            "source_title": "Visa Overview",
            "evidence": "Evidence available.",
            "confidence": 0.9,
            "status": "verified",
        }],
        "sources": [{
            "url": "https://example.com/source",
            "title": "Visa Overview",
            "publisher": "Example",
            "relevance": "high",
        }],
    })
    output_dir = tmp_path / "projects" / "proj-123"
    output_dir.mkdir(parents=True, exist_ok=True)
    file_path = output_dir / "research.json"
    project.model_dump_json(indent=2)
    file_path.write_text(project.model_dump_json(indent=2), encoding="utf-8")
    assert file_path.exists()
    assert file_path.read_text(encoding="utf-8").startswith('{')
