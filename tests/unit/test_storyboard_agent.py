import json

import pytest
from pydantic import ValidationError

from app.agents.storyboard_agent import StoryboardAgent
from app.graph.state import VideoState
from app.graph.workflow import node_storyboard
from app.models.fact_check import ClaimStatus, FactCheckedClaim, FactCheckResult, RecommendedAction
from app.models.research import ResearchProject
from app.models.script import Script, ScriptSection
from app.models.storyboard import Storyboard, StoryboardScene


class FakeModel:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.calls = 0

    def invoke(self, messages):
        self.calls += 1
        payload = self.payloads[min(self.calls - 1, len(self.payloads) - 1)]
        return type("Response", (), {"content": payload})()


def make_script():
    sections = [
        ScriptSection(id="setup", heading="Setup", narration="The setup explains the payment network.", claim_ids=["claim_001"]),
        ScriptSection(id="example", heading="Example", narration="A customer taps a card at a small cafe.", claim_ids=[]),
        ScriptSection(id="mechanism", heading="Mechanism", narration="The mechanism connects banks through a network.", claim_ids=["claim_001"]),
        ScriptSection(id="complexity", heading="Complexity", narration="The process repeats across many transactions.", claim_ids=["claim_001"]),
        ScriptSection(id="insight", heading="Insight", narration="The surprising insight is that the network need not lend money.", claim_ids=["claim_001"]),
        ScriptSection(id="takeaway", heading="Takeaway", narration="The takeaway is simple: movement can create network value.", claim_ids=["claim_001"]),
    ]
    script = Script(
        topic="How Visa Makes Money",
        title="The Payment Network",
        hook="A card payment hides a complex network behind a simple tap.",
        sections=sections,
        conclusion="That is how the payment network can matter without being the lender.",
        factual_claim_ids=["claim_001"],
    )
    script.estimated_duration_seconds = 40
    return script


def make_fact_check(*statuses):
    claims = []
    for index, status in enumerate(statuses, start=1):
        claims.append(FactCheckedClaim(
            claim_id=f"claim_{index:03d}",
            original_claim=f"Verified fact {index}.",
            status=status,
            confidence=0.9 if status == ClaimStatus.VERIFIED else 0.2,
            reasoning="Evidence was evaluated.",
            supporting_sources=["https://www.sec.gov/report"] if status == ClaimStatus.VERIFIED else [],
            recommended_action=RecommendedAction.ACCEPT if status == ClaimStatus.VERIFIED else RecommendedAction.RESEARCH_MORE,
        ))
    counts = {status: sum(claim.status == status for claim in claims) for status in ClaimStatus}
    return FactCheckResult(
        project_id="storyboard-test",
        total_claims=len(claims),
        verified_claims=counts[ClaimStatus.VERIFIED],
        needs_review_claims=counts[ClaimStatus.NEEDS_REVIEW],
        rejected_claims=counts[ClaimStatus.REJECTED],
        claims=claims,
        overall_status=ClaimStatus.VERIFIED if counts[ClaimStatus.VERIFIED] == len(claims) else ClaimStatus.NEEDS_REVIEW,
        needs_more_research=counts[ClaimStatus.VERIFIED] != len(claims),
    )


def make_payload(*, claim_ids=None, duration=5):
    claim_ids = claim_ids if claim_ids is not None else ["claim_001"]
    narration = [
        make_script().hook,
        *(section.narration for section in make_script().sections),
        make_script().conclusion,
    ]
    scenes = []
    for index, text in enumerate(narration, start=1):
        scenes.append({
            "id": f"scene_{index:03d}",
            "duration_seconds": duration,
            "narration": text,
            "visual_description": "A customer and merchant use a payment terminal while a simple transaction diagram builds.",
            "on_screen_text": "PAYMENT FLOW",
            "background": "cafe_01",
            "characters": ["customer_01", "merchant_01"],
            "props": ["payment_terminal_01", "card_01"],
            "camera": "medium shot -> slow push-in",
            "transition": "fade",
            "claim_ids": claim_ids if index != 2 else [],
        })
    return json.dumps({"title": "The Payment Network", "scenes": scenes})


def test_storyboard_models_validate_and_calculate_duration():
    storyboard = Storyboard.model_validate({
        "title": "Payment Flow",
        "scenes": [{
            "id": "scene_001",
            "duration_seconds": 8,
            "narration": "A customer taps a card.",
            "visual_description": "A terminal receives the tap.",
            "background": "cafe",
            "claim_ids": ["claim_001"],
        }],
    })
    assert storyboard.total_duration_seconds == 8
    assert storyboard.estimated_duration_seconds == 8


def test_multiple_scenes_and_character_ids():
    storyboard = StoryboardAgent(FakeModel([make_payload()])).create(make_script(), make_fact_check(ClaimStatus.VERIFIED))
    assert len(storyboard.scenes) == 8
    assert storyboard.scenes[0].characters == storyboard.scenes[1].characters


def test_claim_traceability_accepts_script_claim_ids():
    storyboard = StoryboardAgent(FakeModel([make_payload()])).create(make_script(), make_fact_check(ClaimStatus.VERIFIED))
    assert "claim_001" in storyboard.scenes[0].claim_ids


def test_unknown_claim_id_rejected():
    with pytest.raises(ValueError, match="unknown Script claim IDs"):
        StoryboardAgent(FakeModel([make_payload(claim_ids=["claim_999"])] )).create(make_script(), make_fact_check(ClaimStatus.VERIFIED))


def test_rejected_claim_id_rejected():
    script = make_script()
    fact_check = make_fact_check(ClaimStatus.REJECTED)
    with pytest.raises(ValueError, match="rejected claim IDs"):
        StoryboardAgent(FakeModel([make_payload()])).create(script, fact_check)


def test_missing_narration_rejected():
    with pytest.raises(ValidationError):
        StoryboardScene(id="scene_001", duration_seconds=8, narration="", visual_description="visual", background="room")


def test_missing_visual_description_rejected():
    with pytest.raises(ValidationError):
        StoryboardScene(id="scene_001", duration_seconds=8, narration="narration", visual_description="", background="room")


def test_invalid_duration_rejected():
    with pytest.raises(ValidationError):
        StoryboardScene(id="scene_001", duration_seconds=20, narration="narration", visual_description="visual", background="room")


def test_total_duration_mismatch_rejected():
    payload = json.loads(make_payload())
    for scene in payload["scenes"]:
        scene["duration_seconds"] = 15
    with pytest.raises(ValueError, match="differs from Script duration"):
        StoryboardAgent(FakeModel([json.dumps(payload)])).create(make_script(), make_fact_check(ClaimStatus.VERIFIED))


def test_script_coverage_rejected():
    payload = json.loads(make_payload())
    payload["scenes"] = payload["scenes"][:-1]
    with pytest.raises(ValueError, match="cover the Script hook or conclusion"):
        StoryboardAgent(FakeModel([json.dumps(payload)])).create(make_script(), make_fact_check(ClaimStatus.VERIFIED))


def test_invalid_model_output_retries():
    writer = StoryboardAgent(FakeModel(["not json", make_payload()]))
    result = writer.create(make_script(), make_fact_check(ClaimStatus.VERIFIED))
    assert len(result.scenes) == 8
    assert writer.model.calls == 2


def test_retry_exhaustion_is_clear():
    with pytest.raises(ValueError, match="failed after 2 attempts"):
        StoryboardAgent(FakeModel(["not json"]), max_retries=2).create(make_script(), make_fact_check(ClaimStatus.VERIFIED))


def test_storyboard_cache_reused(tmp_path):
    model = FakeModel([make_payload()])
    agent = StoryboardAgent(model)
    first = agent.create(make_script(), make_fact_check(ClaimStatus.VERIFIED), project_dir=tmp_path)
    model.calls = 0
    second = agent.create(make_script(), make_fact_check(ClaimStatus.VERIFIED), project_dir=tmp_path)
    assert first.model_dump() == second.model_dump()
    assert model.calls == 0


def test_invalid_cache_regenerates(tmp_path):
    (tmp_path / "storyboard.json").write_text("{invalid", encoding="utf-8")
    model = FakeModel([make_payload()])
    result = StoryboardAgent(model).create(make_script(), make_fact_check(ClaimStatus.VERIFIED), project_dir=tmp_path)
    assert result.scenes
    assert model.calls == 1
    assert StoryboardAgent.load_storyboard(tmp_path) is not None


def test_storyboard_persistence(tmp_path):
    agent = StoryboardAgent(FakeModel([make_payload()]))
    agent.create(make_script(), make_fact_check(ClaimStatus.VERIFIED), project_dir=tmp_path)
    assert (tmp_path / "storyboard.json").exists()


def test_storyboard_does_not_introduce_unsupported_claims():
    storyboard = StoryboardAgent(FakeModel([make_payload()])).create(make_script(), make_fact_check(ClaimStatus.VERIFIED))
    referenced = {claim_id for scene in storyboard.scenes for claim_id in scene.claim_ids}
    assert referenced <= {"claim_001"}


def test_langgraph_state_receives_storyboard(monkeypatch, tmp_path):
    script = make_script()
    fact_check = make_fact_check(ClaimStatus.VERIFIED)
    storyboard = StoryboardAgent(FakeModel([make_payload()])).create(script, fact_check)

    class StubAgent:
        def create(self, script, fact_check, *, project_id, project_dir):
            return storyboard

    monkeypatch.setattr("app.graph.workflow.StoryboardAgent", StubAgent)
    monkeypatch.chdir(tmp_path)
    state = VideoState(project_id="storyboard-test", topic=script.topic, script=script, fact_check=fact_check)
    updated = node_storyboard(state)
    assert updated["storyboard"] == storyboard
    assert updated["errors"] == []
