from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import settings
from app.graph.routing import should_continue_fact_check
from app.graph.state import VideoState, PipelineStatus
from app.llm.factory import create_model, get_available_provider_names
from app.models.research import ClaimStatus, ResearchClaim, ResearchProject
from app.models.storyboard import Storyboard, StoryboardScene
from app.renderer.video import render_test_frame
from app.utils.files import ensure_directory, read_json, write_json


def test_settings_loads_from_environment(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("LLM_MODEL", "gpt-4o-mini")
    monkeypatch.setenv("AUTO_APPROVE", "true")
    settings.reload()

    assert settings.llm_provider == "openai"
    assert settings.llm_model == "gpt-4o-mini"
    assert settings.auto_approve is True


def test_llm_factory_returns_model_for_openai(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("LLM_MODEL", "gpt-4o-mini")
    model = create_model()
    assert model is not None
    assert get_available_provider_names() == ["openai", "anthropic", "gemini"]


def test_video_state_default_values():
    state = VideoState(project_id="proj-123", topic="How Visa makes money")
    assert state["project_id"] == "proj-123"
    assert state["topic"] == "How Visa makes money"
    assert state["status"] == PipelineStatus.PENDING
    assert state["errors"] == []


def test_fact_check_routing_logic():
    assert should_continue_fact_check(2, 3) is True
    assert should_continue_fact_check(3, 3) is False
    assert should_continue_fact_check(0, 0) is False


def test_research_claim_validation():
    data = {
        "claim": "Visa earns revenue primarily from payments processing fees.",
        "importance": "high",
        "source_url": "https://example.com/source",
        "source_title": "Visa Annual Report",
        "evidence": "Visa discloses fee-based revenue from payment processing.",
        "confidence": 0.86,
        "status": "verified",
    }
    claim = ResearchClaim.model_validate(data)
    assert claim.status == ClaimStatus.VERIFIED
    assert claim.confidence > 0.8

    with pytest.raises(ValidationError):
        ResearchClaim.model_validate({
            "claim": "bad",
            "importance": "high",
            "source_url": "not-a-url",
            "source_title": "title",
            "evidence": "evidence",
            "confidence": 1.5,
            "status": "unknown",
        })


def test_research_project_validation():
    project = ResearchProject.model_validate({
        "topic": "How Visa makes money",
        "key_questions": ["How does Visa generate revenue?"],
        "sections": ["Business model"],
        "claims": [{
            "claim": "Visa earns processing fees.",
            "importance": "high",
            "source_url": "https://example.com/source",
            "source_title": "Visa Annual Report",
            "evidence": "Income from payment processing.",
            "confidence": 0.9,
            "status": "verified",
        }],
        "sources": ["https://example.com/source"],
    })
    assert project.topic == "How Visa makes money"
    assert len(project.claims) == 1


def test_storyboard_validation():
    scene = StoryboardScene.model_validate({
        "id": 1,
        "duration_seconds": 8,
        "narration": "Imagine paying with a card.",
        "visual_description": "A card is swiped at a checkout terminal.",
        "on_screen_text": "PAYMENT FLOW",
        "background": "store",
        "characters": ["customer"],
        "props": ["card"],
        "camera": "slow_zoom_in",
        "transition": "fade",
    })
    storyboard = Storyboard.model_validate({"scenes": [scene]})
    assert storyboard.scenes[0].id == 1
    assert storyboard.total_duration_seconds == 8


def test_renderer_can_generate_a_frame(tmp_path):
    frame = render_test_frame(output_path=tmp_path / "sample.png")
    assert frame.exists()
    assert frame.suffix == ".png"


def test_file_utils_roundtrip(tmp_path):
    target_dir = tmp_path / "nested" / "project"
    ensure_directory(target_dir)
    payload = {"project_id": "abc", "status": "ok"}
    file_path = write_json(target_dir / "state.json", payload)
    result = read_json(file_path)
    assert result == payload


def test_caching_logic_and_file_state(tmp_path):
    project_dir = tmp_path / "project"
    ensure_directory(project_dir)
    cache_file = project_dir / "cache.json"
    write_json(cache_file, {"topic": "Visa", "status": "complete"})
    cached = read_json(cache_file)
    assert cached["status"] == "complete"


def test_pipeline_state_is_usable():
    state = VideoState(project_id="proj-456", topic="Test topic")
    assert "project_id" in state
    assert "status" in state
    assert state["status"] == PipelineStatus.PENDING
