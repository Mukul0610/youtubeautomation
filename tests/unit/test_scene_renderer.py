from pathlib import Path

import pytest

from app.agents.asset_agent import AssetAgent
from app.agents.tts_agent import TTSAgent
from app.assets.providers import MockAssetProvider
from app.models.rendered import RenderedScenes
from app.models.storyboard import Storyboard, StoryboardScene
from app.renderer.scene import SceneRenderer
from app.tts.providers import MockTTSProvider
from app.graph.state import VideoState
from app.graph.workflow import node_render_scenes


def make_storyboard():
    return Storyboard(scenes=[
        StoryboardScene(
            id="scene_001", duration_seconds=5,
            narration="A customer taps a card at a store.",
            visual_description="A customer taps a payment terminal.",
            background="retail_store_01", characters=["customer_01"],
            props=["payment_terminal_01"], on_screen_text="PAYMENT FLOW",
            camera="slow zoom in", transition="fade",
        ),
        StoryboardScene(
            id="scene_002", duration_seconds=5,
            narration="The payment moves through the network.",
            visual_description="Arrows connect the store to a network.",
            background="retail_store_01", characters=["merchant_01"],
            props=["payment_terminal_01"], camera="pan right",
        ),
    ])


def prepare_project(tmp_path):
    storyboard = make_storyboard()
    assets = AssetAgent(provider=MockAssetProvider())
    registry = assets.generate(storyboard, project_id="render-test", project_dir=tmp_path)
    tts = TTSAgent(provider=MockTTSProvider())
    tts_result = tts.synthesize(storyboard, project_id="render-test", project_dir=tmp_path)
    renderer = SceneRenderer(width=160, height=90, fps=5)
    return storyboard, registry, tts_result, renderer


def test_basic_scene_rendering_and_metadata(tmp_path):
    storyboard, registry, tts_result, renderer = prepare_project(tmp_path)
    result = renderer.render_project(storyboard, tts_result, registry, tmp_path, "render-test")
    assert len(result.scenes) == 2
    for scene in result.scenes:
        path = tmp_path / scene.video_path
        assert path.exists()
        assert path.stat().st_size > 0
        assert scene.width == 160
        assert scene.height == 90
        assert scene.fps == 5
        assert scene.audio_path.endswith(".wav")
    assert (tmp_path / "rendered_scenes.json").exists()


def test_audio_duration_is_authoritative(tmp_path):
    storyboard, registry, tts_result, renderer = prepare_project(tmp_path)
    result = renderer.render_project(storyboard, tts_result, registry, tmp_path, "render-test")
    assert result.scenes[0].duration_seconds == tts_result.scenes[0].duration_seconds


def test_missing_asset_is_rejected(tmp_path):
    storyboard, registry, tts_result, renderer = prepare_project(tmp_path)
    registry.assets = [asset for asset in registry.assets if asset.asset_id != "customer_01"]
    with pytest.raises(ValueError, match="missing visual asset"):
        renderer.render_project(storyboard, tts_result, registry, tmp_path, "render-test")


def test_missing_audio_is_rejected(tmp_path):
    storyboard, registry, tts_result, renderer = prepare_project(tmp_path)
    (tmp_path / tts_result.scenes[0].audio_path).unlink()
    with pytest.raises(ValueError, match="missing audio"):
        renderer.render_project(storyboard, tts_result, registry, tmp_path, "render-test")


def test_cache_reuses_unchanged_scene(tmp_path):
    storyboard, registry, tts_result, renderer = prepare_project(tmp_path)
    first = renderer.render_project(storyboard, tts_result, registry, tmp_path, "render-test")
    first_mtime = [(tmp_path / scene.video_path).stat().st_mtime_ns for scene in first.scenes]
    second = renderer.render_project(storyboard, tts_result, registry, tmp_path, "render-test")
    second_mtime = [(tmp_path / scene.video_path).stat().st_mtime_ns for scene in second.scenes]
    assert first.model_dump() == second.model_dump()
    assert first_mtime == second_mtime


def test_changed_scene_fingerprint_rerenders_only_that_scene(tmp_path):
    storyboard, registry, tts_result, renderer = prepare_project(tmp_path)
    first = renderer.render_project(storyboard, tts_result, registry, tmp_path, "render-test")
    first_mtime = [(tmp_path / scene.video_path).stat().st_mtime_ns for scene in first.scenes]
    storyboard.scenes[0].on_screen_text = "UPDATED"
    second = renderer.render_project(storyboard, tts_result, registry, tmp_path, "render-test")
    second_mtime = [(tmp_path / scene.video_path).stat().st_mtime_ns for scene in second.scenes]
    assert second_mtime[0] != first_mtime[0]
    assert second_mtime[1] == first_mtime[1]


def test_rendered_metadata_loads(tmp_path):
    storyboard, registry, tts_result, renderer = prepare_project(tmp_path)
    renderer.render_project(storyboard, tts_result, registry, tmp_path, "render-test")
    loaded = RenderedScenes.model_validate_json((tmp_path / "rendered_scenes.json").read_text())
    assert len(loaded.scenes) == 2


def test_langgraph_state_receives_rendered_scenes(monkeypatch, tmp_path):
    storyboard, registry, tts_result, renderer = prepare_project(tmp_path)
    expected = renderer.render_project(storyboard, tts_result, registry, tmp_path, "render-test")

    class StubRenderer:
        def render_project(self, storyboard, tts_result, registry, project_dir, project_id):
            return expected

    monkeypatch.setattr("app.graph.workflow.SceneRenderer", StubRenderer)
    monkeypatch.chdir(tmp_path)
    state = VideoState(
        project_id="render-test", topic="Demo", storyboard=storyboard,
        tts_result=tts_result, visual_assets=registry,
    )
    updated = node_render_scenes(state)
    assert updated["rendered_scenes"] == expected
    assert updated["errors"] == []
