from pathlib import Path

import pytest
from PIL import Image

from app.agents.asset_agent import AssetAgent
from app.agents.thumbnail_agent import ThumbnailAgent
from app.assets.providers import MockAssetProvider
from app.graph.state import VideoState
from app.graph.workflow import node_thumbnail
from app.models.final_video import FinalVideo
from app.models.storyboard import Storyboard, StoryboardScene
from app.thumbnails.providers import MockThumbnailProvider, ThumbnailProvider
from tests.unit.test_asset_agent import make_fact_check


def make_storyboard():
    return Storyboard(scenes=[
        StoryboardScene(id="scene_001", duration_seconds=5, narration="A customer taps a card.", visual_description="A payment scene.", background="retail_store_01", characters=["merchant_01", "customer_01"], props=["payment_terminal_01"]),
    ])


def make_final_video():
    return FinalVideo(project_id="thumb-test", video_path="final_video.mp4", duration_seconds=5, width=1280, height=720, fps=30, scene_count=1, file_size_bytes=10, composition_fingerprint="video-fp", scene_ids=["scene_001"])


def make_registry(tmp_path):
    return AssetAgent(provider=MockAssetProvider()).generate(make_storyboard(), fact_check=make_fact_check(), project_id="thumb-test", project_dir=tmp_path)


def test_thumbnail_generation_dimensions_and_png(tmp_path):
    result = ThumbnailAgent().generate("thumb-test", "How Visa Makes Money Without Lending You Money", make_registry(tmp_path), make_storyboard(), final_video=make_final_video(), project_dir=tmp_path)
    path = tmp_path / result.thumbnail_path
    assert path.exists()
    with Image.open(path) as image:
        assert image.size == (1280, 720)
        assert image.format == "PNG"


def test_thumbnail_metadata_contains_text_assets_and_template(tmp_path):
    registry = make_registry(tmp_path)
    result = ThumbnailAgent().generate("thumb-test", "How Visa Makes Money Without Lending You Money", registry, make_storyboard(), final_video=make_final_video(), project_dir=tmp_path)
    assert result.title_text == "HOW VISA\nMAKES MONEY"
    assert result.asset_ids
    assert result.template_id == "finance_explainer"
    assert (tmp_path / "thumbnail.json").exists()


def test_thumbnail_cache_reuses_unchanged_output(tmp_path):
    agent = ThumbnailAgent()
    registry = make_registry(tmp_path)
    first = agent.generate("thumb-test", "How Visa Makes Money", registry, make_storyboard(), final_video=make_final_video(), project_dir=tmp_path)
    mtime = (tmp_path / "thumbnail.png").stat().st_mtime_ns
    second = agent.generate("thumb-test", "How Visa Makes Money", registry, make_storyboard(), final_video=make_final_video(), project_dir=tmp_path)
    assert first.model_dump() == second.model_dump()
    assert (tmp_path / "thumbnail.png").stat().st_mtime_ns == mtime


def test_thumbnail_fingerprint_invalidates_on_topic_change(tmp_path):
    agent = ThumbnailAgent()
    registry = make_registry(tmp_path)
    first = agent.generate("thumb-test", "How Visa Makes Money", registry, make_storyboard(), final_video=make_final_video(), project_dir=tmp_path)
    second = agent.generate("thumb-test", "How Banks Make Money", registry, make_storyboard(), final_video=make_final_video(), project_dir=tmp_path)
    assert first.fingerprint != second.fingerprint


def test_missing_asset_fails_clearly(tmp_path):
    registry = make_registry(tmp_path)
    registry.assets = [asset for asset in registry.assets if asset.asset_id != "merchant_01"]
    with pytest.raises(ValueError, match="thumbnail asset"):
        ThumbnailAgent().generate("thumb-test", "How Visa Makes Money", registry, make_storyboard(), final_video=make_final_video(), project_dir=tmp_path)


def test_missing_previous_artifact_fails(tmp_path):
    with pytest.raises(ValueError, match="composed final video"):
        ThumbnailAgent().generate("thumb-test", "How Visa Makes Money", make_registry(tmp_path), make_storyboard(), project_dir=tmp_path)


def test_invalid_provider_output_is_rejected(tmp_path):
    class BadProvider(ThumbnailProvider):
        name = "bad"
        def generate(self, request):
            Path(request.output_path).write_bytes(b"invalid")
            return None

    with pytest.raises(ValueError, match="invalid thumbnail output"):
        ThumbnailAgent(provider=BadProvider()).generate("thumb-test", "How Visa Makes Money", make_registry(tmp_path), make_storyboard(), final_video=make_final_video(), project_dir=tmp_path)


def test_graph_state_receives_thumbnail(monkeypatch, tmp_path):
    registry = make_registry(tmp_path)
    storyboard = make_storyboard()
    final_video = make_final_video()
    expected = ThumbnailAgent().generate("thumb-test", "How Visa Makes Money", registry, storyboard, final_video=final_video, project_dir=tmp_path)

    class StubAgent:
        def generate(self, project_id, topic, registry, storyboard, *, final_video, project_dir):
            return expected

    monkeypatch.setattr("app.graph.workflow.ThumbnailAgent", StubAgent)
    monkeypatch.chdir(tmp_path)
    state = VideoState(project_id="thumb-test", topic="How Visa Makes Money", visual_assets=registry, storyboard=storyboard, final_video=final_video)
    updated = node_thumbnail(state)
    assert updated["thumbnail"] == expected
    assert updated["status"] == "completed"
    assert updated["errors"] == []
