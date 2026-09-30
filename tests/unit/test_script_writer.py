import json

import pytest

from app.agents.script_writer import ScriptWriter
from app.graph.state import VideoState
from app.graph.workflow import node_script
from app.models.fact_check import FactCheckedClaim, FactCheckResult, RecommendedAction
from app.models.research import ClaimStatus, ResearchProject
from app.models.script import Script, ScriptQualityStatus, ScriptSection


class FakeModel:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.calls = 0

    def invoke(self, messages):
        self.calls += 1
        payload = self.payloads[min(self.calls - 1, len(self.payloads) - 1)]
        return type("Response", (), {"content": payload})()


def make_fact_check(*statuses):
    claims = []
    for index, status in enumerate(statuses, start=1):
        claims.append(FactCheckedClaim(
            claim_id=f"claim_{index:03d}",
            original_claim=f"Verified finance fact {index}.",
            status=status,
            confidence=0.9 if status == ClaimStatus.VERIFIED else 0.3,
            reasoning="Evidence was evaluated.",
            supporting_sources=["https://www.sec.gov/report"] if status == ClaimStatus.VERIFIED else [],
            recommended_action=(RecommendedAction.ACCEPT if status == ClaimStatus.VERIFIED else RecommendedAction.RESEARCH_MORE),
        ))
    counts = {status: sum(claim.status == status for claim in claims) for status in ClaimStatus}
    return FactCheckResult(
        project_id="script-test",
        total_claims=len(claims),
        verified_claims=counts[ClaimStatus.VERIFIED],
        needs_review_claims=counts[ClaimStatus.NEEDS_REVIEW],
        rejected_claims=counts[ClaimStatus.REJECTED],
        claims=claims,
        overall_status=ClaimStatus.VERIFIED if len(claims) == counts[ClaimStatus.VERIFIED] else ClaimStatus.NEEDS_REVIEW,
        needs_more_research=counts[ClaimStatus.VERIFIED] != len(claims),
    )


def make_research():
    return ResearchProject(topic="How Visa Makes Money", key_questions=["How does Visa earn revenue?"])


def make_payload(*, claim_id="claim_001", words=190, include_claim=True):
    paragraph = "word " * words
    sections = []
    for index, heading in enumerate(["Setup", "Relatable Example", "Financial Mechanism", "How It Works", "Why It Matters", "Clear Takeaway"], start=1):
        sections.append({
            "id": f"section_{index}",
            "heading": heading,
            "purpose": "Explain the idea clearly.",
            "narration": paragraph,
            "visual_intent": "Show a simple animated payment flow.",
            "claim_ids": [claim_id] if include_claim else [],
        })
    return json.dumps({
        "topic": "How Visa Makes Money",
        "title": "The Payment Network Behind Your Card",
        "alternate_titles": ["How Visa Earns Without Lending"],
        "hook": "Everyday payments hide a business model most people never see.",
        "sections": sections,
        "conclusion": "The simple takeaway is that the network can earn from movement without being the lender.",
        "factual_claim_ids": [claim_id] if include_claim else [],
    })


def test_script_models_calculate_word_count_and_duration():
    script = Script.model_validate({
        "topic": "Topic",
        "title": "Title",
        "hook": "Hook",
        "sections": [ScriptSection(heading="Setup", content="one two three")],
        "conclusion": "Conclusion",
    })
    assert script.estimated_word_count == 5
    assert script.estimated_duration_seconds > 0


def test_quality_report_accepts_traceable_script():
    fact_check = make_fact_check(ClaimStatus.VERIFIED)
    script = ScriptWriter(FakeModel([]))._parse_script(make_payload())
    report = ScriptWriter.quality_report(script, fact_check)
    assert report.status == ScriptQualityStatus.PASS
    assert report.rejected_claim_ids == []
    assert report.word_count >= 1100


def test_rejected_claim_detection():
    fact_check = make_fact_check(ClaimStatus.REJECTED)
    script = ScriptWriter(FakeModel([]))._parse_script(make_payload())
    report = ScriptWriter.quality_report(script, fact_check)
    assert report.status == ScriptQualityStatus.FAIL
    assert "claim_001" in report.rejected_claim_ids


def test_missing_claim_detection():
    fact_check = make_fact_check(ClaimStatus.VERIFIED)
    script = ScriptWriter(FakeModel([]))._parse_script(make_payload(claim_id="claim_999"))
    report = ScriptWriter.quality_report(script, fact_check)
    assert report.status == ScriptQualityStatus.FAIL
    assert any("not present" in error for error in report.errors)


def test_needs_review_claim_detection():
    fact_check = make_fact_check(ClaimStatus.NEEDS_REVIEW)
    script = ScriptWriter(FakeModel([]))._parse_script(make_payload())
    report = ScriptWriter.quality_report(script, fact_check)
    assert report.status == ScriptQualityStatus.FAIL
    assert any("not verified" in error for error in report.errors)


def test_too_short_script_fails_quality_report():
    fact_check = make_fact_check(ClaimStatus.VERIFIED)
    script = ScriptWriter(FakeModel([]))._parse_script(make_payload(words=10))
    report = ScriptWriter.quality_report(script, fact_check)
    assert report.status == ScriptQualityStatus.FAIL


def test_too_long_script_fails_quality_report():
    fact_check = make_fact_check(ClaimStatus.VERIFIED)
    script = ScriptWriter(FakeModel([]))._parse_script(make_payload(words=350))
    report = ScriptWriter.quality_report(script, fact_check)
    assert report.status == ScriptQualityStatus.FAIL


def test_script_generation_with_mocked_llm_and_persistence(tmp_path):
    writer = ScriptWriter(FakeModel([make_payload()]))
    script = writer.write(make_research(), make_fact_check(ClaimStatus.VERIFIED), project_dir=tmp_path)
    assert script.estimated_word_count >= 1100
    assert (tmp_path / "script.json").exists()
    assert (tmp_path / "script.txt").exists()


def test_invalid_output_retries_then_succeeds(tmp_path):
    writer = ScriptWriter(FakeModel(["not json", make_payload()]))
    script = writer.write(make_research(), make_fact_check(ClaimStatus.VERIFIED), project_dir=tmp_path)
    assert script.title == "The Payment Network Behind Your Card"
    assert writer.model.calls == 2


def test_retry_failure_is_explicit():
    writer = ScriptWriter(FakeModel([make_payload(words=10)]), max_retries=2)
    with pytest.raises(ValueError, match="failed after 2 attempts"):
        writer.write(make_research(), make_fact_check(ClaimStatus.VERIFIED))


def test_cached_script_avoids_llm_call(tmp_path):
    model = FakeModel([make_payload()])
    writer = ScriptWriter(model)
    first = writer.write(make_research(), make_fact_check(ClaimStatus.VERIFIED), project_dir=tmp_path)
    model.calls = 0
    second = writer.write(make_research(), make_fact_check(ClaimStatus.VERIFIED), project_dir=tmp_path)
    assert first.model_dump() == second.model_dump()
    assert model.calls == 0


def test_no_verified_claims_fail_before_llm_call():
    model = FakeModel([make_payload()])
    with pytest.raises(ValueError, match="verified claims"):
        ScriptWriter(model).write(make_research(), make_fact_check(ClaimStatus.NEEDS_REVIEW))
    assert model.calls == 0


def test_langgraph_script_node_updates_state(monkeypatch, tmp_path):
    research = make_research()
    fact_check = make_fact_check(ClaimStatus.VERIFIED)
    script = ScriptWriter(FakeModel([make_payload()])).write(research, fact_check)

    class StubWriter:
        def write(self, research, fact_check, *, project_id, project_dir):
            return script

    monkeypatch.setattr("app.graph.workflow.ScriptWriter", StubWriter)
    monkeypatch.chdir(tmp_path)
    state = VideoState(project_id="script-test", topic=research.topic, research=research, fact_check=fact_check)
    updated = node_script(state)
    assert updated["script"] == script
    assert updated["errors"] == []
