import json

import pytest
from PIL import Image

from app.agents.asset_agent import AssetAgent
from app.assets.providers import MockAssetProvider, VisualAssetProvider, build_asset_provider, validate_image
from app.graph.state import VideoState
from app.graph.workflow import node_visual_assets
from app.models.assets import AssetType, ChartAssetRequest, DiagramAssetRequest
from app.models.fact_check import ClaimStatus, FactCheckedClaim, FactCheckResult, RecommendedAction
from app.models.storyboard import Storyboard, StoryboardScene


class CountingProvider(MockAssetProvider):
    def __init__(self, failures=0):
        self.calls = []
        self.failures = failures

    def generate_asset(self, request, output_path, width, height):
        self.calls.append(request.asset_id)
        if self.failures:
            self.failures -= 1
            raise RuntimeError("provider failure")
        return super().generate_asset(request, output_path, width, height)


class AlwaysFailProvider(VisualAssetProvider):
    name = "failing"

    def generate_asset(self, request, output_path, width, height):
        raise RuntimeError("provider unavailable")


def make_storyboard(claim_ids=None):
    claim_ids = claim_ids or ["claim_001"]
    return Storyboard(scenes=[
        StoryboardScene(id="scene_001", duration_seconds=5, narration="A customer taps a card.", visual_description="A merchant and customer use a terminal.", background="retail_store_01", characters=["merchant_01", "customer_01"], props=["payment_terminal_01"], claim_ids=claim_ids),
        StoryboardScene(id="scene_002", duration_seconds=5, narration="The same customer sees the payment move.", visual_description="Arrows connect the terminal and banks.", background="retail_store_01", characters=["merchant_01", "customer_01"], props=["payment_terminal_01"], claim_ids=claim_ids),
    ])


def make_fact_check(status=ClaimStatus.VERIFIED):
    claim = FactCheckedClaim(
        claim_id="claim_001",
        original_claim="A verified payment fact.",
        status=status,
        confidence=0.9 if status == ClaimStatus.VERIFIED else 0.2,
        reasoning="Evidence evaluated.",
        recommended_action=RecommendedAction.ACCEPT if status == ClaimStatus.VERIFIED else RecommendedAction.RESEARCH_MORE,
    )
    return FactCheckResult(
        project_id="asset-test",
        total_claims=1,
        verified_claims=int(status == ClaimStatus.VERIFIED),
        needs_review_claims=int(status == ClaimStatus.NEEDS_REVIEW),
        rejected_claims=int(status == ClaimStatus.REJECTED),
        claims=[claim],
        overall_status=status,
        needs_more_research=status != ClaimStatus.VERIFIED,
    )


def test_asset_planner_creates_character_background_prop_requests():
    requests = AssetAgent(provider=MockAssetProvider()).plan(make_storyboard(), make_fact_check())
    assert {request.asset_id for request in requests} == {"retail_store_01", "merchant_01", "customer_01", "payment_terminal_01"}
    assert {request.type for request in requests} == {AssetType.BACKGROUND, AssetType.CHARACTER, AssetType.PROP}


def test_asset_ids_are_deterministic_and_deduplicated():
    first = AssetAgent(provider=MockAssetProvider()).plan(make_storyboard(), make_fact_check())
    second = AssetAgent(provider=MockAssetProvider()).plan(make_storyboard(), make_fact_check())
    assert [request.asset_id for request in first] == [request.asset_id for request in second]
    assert len(first) == 4


def test_mock_provider_creates_valid_image(tmp_path):
    request = AssetAgent(provider=MockAssetProvider()).plan(make_storyboard(), make_fact_check())[0]
    path = tmp_path / "asset.png"
    MockAssetProvider().generate_asset(request, path, 320, 180)
    assert validate_image(path) == (320, 180, "PNG")
    with Image.open(path) as image:
        assert image.size == (320, 180)


def test_registry_creation_and_persistence(tmp_path):
    registry = AssetAgent(provider=MockAssetProvider()).generate(make_storyboard(), fact_check=make_fact_check(), project_id="asset-test", project_dir=tmp_path)
    path = tmp_path / "assets" / "registry.json"
    assert path.exists()
    loaded = AssetAgent.load_registry(tmp_path)
    assert loaded is not None
    assert len(registry.assets) == 4
    assert len(loaded.assets) == 4


def test_cache_reuses_existing_assets(tmp_path):
    provider = CountingProvider()
    agent = AssetAgent(provider=provider)
    agent.generate(make_storyboard(), fact_check=make_fact_check(), project_id="asset-test", project_dir=tmp_path)
    provider.calls.clear()
    agent.generate(make_storyboard(), fact_check=make_fact_check(), project_id="asset-test", project_dir=tmp_path)
    assert provider.calls == []


def test_missing_asset_regenerates_only_one(tmp_path):
    provider = CountingProvider()
    agent = AssetAgent(provider=provider)
    agent.generate(make_storyboard(), fact_check=make_fact_check(), project_id="asset-test", project_dir=tmp_path)
    provider.calls.clear()
    (tmp_path / "assets" / "props" / "payment_terminal_01.png").unlink()
    agent.generate(make_storyboard(), fact_check=make_fact_check(), project_id="asset-test", project_dir=tmp_path)
    assert provider.calls == ["payment_terminal_01"]


def test_corrupt_asset_regenerates_only_one(tmp_path):
    provider = CountingProvider()
    agent = AssetAgent(provider=provider)
    agent.generate(make_storyboard(), fact_check=make_fact_check(), project_id="asset-test", project_dir=tmp_path)
    provider.calls.clear()
    (tmp_path / "assets" / "characters" / "merchant_01.png").write_bytes(b"corrupt")
    agent.generate(make_storyboard(), fact_check=make_fact_check(), project_id="asset-test", project_dir=tmp_path)
    assert provider.calls == ["merchant_01"]


def test_unknown_claim_id_rejected():
    with pytest.raises(ValueError, match="unknown claim IDs"):
        AssetAgent(provider=MockAssetProvider()).plan(make_storyboard(["claim_999"]), make_fact_check())


def test_rejected_claim_id_rejected():
    with pytest.raises(ValueError, match="rejected claim IDs"):
        AssetAgent(provider=MockAssetProvider()).plan(make_storyboard(), make_fact_check(ClaimStatus.REJECTED))


def test_chart_and_diagram_requests_are_structured_and_traceable():
    chart = ChartAssetRequest(asset_id="chart_001", chart_type="bar", title="Revenue", labels=["A"], values=[1], source_claim_ids=["claim_001"])
    diagram = DiagramAssetRequest(asset_id="diagram_001", nodes=["Merchant", "Network"], edges=[("Merchant", "Network")], claim_ids=["claim_001"])
    assert chart.source_claim_ids == ["claim_001"]
    assert diagram.claim_ids == ["claim_001"]
    with pytest.raises(ValueError):
        ChartAssetRequest(asset_id="bad", chart_type="bar", title="Bad", labels=["A"], values=[1, 2])


def test_provider_factory_and_retry():
    assert isinstance(build_asset_provider("mock"), MockAssetProvider)
    provider = CountingProvider(failures=2)
    agent = AssetAgent(provider=provider)
    requests = agent.plan(make_storyboard(), make_fact_check())
    agent._generate_one(requests[0], __import__("pathlib").Path("/tmp/asset-retry.png"))
    assert provider.calls[:3] == [requests[0].asset_id] * 3


def test_retry_exhaustion_raises(tmp_path):
    with pytest.raises(RuntimeError, match="failed for retail_store_01"):
        AssetAgent(provider=AlwaysFailProvider(), max_retries=2).generate(make_storyboard(), fact_check=make_fact_check(), project_id="asset-test", project_dir=tmp_path)


def test_graph_state_receives_visual_assets(monkeypatch, tmp_path):
    storyboard = make_storyboard()
    expected = AssetAgent(provider=MockAssetProvider()).generate(storyboard, fact_check=make_fact_check(), project_id="asset-test", project_dir=tmp_path)

    class StubAgent:
        def generate(self, storyboard, *, fact_check, project_id, project_dir):
            return expected

    monkeypatch.setattr("app.graph.workflow.AssetAgent", StubAgent)
    monkeypatch.chdir(tmp_path)
    state = VideoState(project_id="asset-test", topic="Demo", storyboard=storyboard, fact_check=make_fact_check())
    updated = node_visual_assets(state)
    assert updated["visual_assets"] == expected
    assert updated["errors"] == []
