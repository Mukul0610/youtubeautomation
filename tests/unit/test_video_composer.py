import json
from pathlib import Path

import pytest

from app.composer.video import VideoComposer
from app.graph.state import VideoState
from app.graph.workflow import node_compose_video
from app.models.final_video import FinalVideo
from app.models.rendered import RenderedScene, RenderedScenes
from app.models.storyboard import Storyboard, StoryboardScene
from app.renderer.scene import SceneRenderer
from app.agents.asset_agent import AssetAgent
from app.tts.providers import MockTTSProvider
from app.agents.tts_agent import TTSAgent
from app.assets.providers import MockAssetProvider


def make_storyboard():
    return Storyboard(scenes=[
        StoryboardScene(id="scene_002", duration_seconds=5, narration="Second scene audio.", visual_description="Network flow.", background="bg_01"),
        StoryboardScene(id="scene_001", duration_seconds=5, narration="First scene audio.", visual_description="Customer payment.", background="bg_01"),
    ])


def make_project(tmp_path):
    storyboard = make_storyboard()
    registry = AssetAgent(provider=MockAssetProvider()).generate(storyboard, project_id="compose-test", project_dir=tmp_path)
    tts_result = TTSAgent(provider=MockTTSProvider()).synthesize(storyboard, project_id="compose-test", project_dir=tmp_path)
    rendered = SceneRenderer(width=160, height=90, fps=5).render_project(storyboard, tts_result, registry, tmp_path, "compose-test")
    return storyboard, rendered


def test_single_and_multiple_scene_composition(tmp_path):
    storyboard, rendered = make_project(tmp_path)
    result = VideoComposer(width=160, height=90, fps=5).compose(storyboard, rendered, tmp_path, "compose-test")
    assert (tmp_path / "final_video.mp4").exists()
    assert result.scene_count == 2
    assert result.scene_ids == ["scene_002", "scene_001"]
    assert result.duration_seconds > 0


def test_storyboard_order_is_canonical(tmp_path):
    storyboard, rendered = make_project(tmp_path)
    rendered.scenes.reverse()
    result = VideoComposer(width=160, height=90, fps=5).compose(storyboard, rendered, tmp_path, "compose-test")
    assert result.scene_ids == ["scene_002", "scene_001"]


def test_missing_scene_rejected(tmp_path):
    storyboard, rendered = make_project(tmp_path)
    rendered.scenes.pop()
    with pytest.raises(ValueError, match="missing from rendered metadata"):
        VideoComposer(width=160, height=90, fps=5).compose(storyboard, rendered, tmp_path, "compose-test")


def test_corrupt_scene_rejected(tmp_path):
    storyboard, rendered = make_project(tmp_path)
    (tmp_path / rendered.scenes[0].video_path).write_bytes(b"bad")
    with pytest.raises(ValueError, match="video is unreadable"):
        VideoComposer(width=160, height=90, fps=5).compose(storyboard, rendered, tmp_path, "compose-test")


def test_metadata_persistence_and_validation(tmp_path):
    storyboard, rendered = make_project(tmp_path)
    VideoComposer(width=160, height=90, fps=5).compose(storyboard, rendered, tmp_path, "compose-test")
    metadata = FinalVideo.model_validate_json((tmp_path / "final_video.json").read_text())
    assert metadata.scene_count == 2
    assert metadata.file_size_bytes > 0
    assert metadata.video_path == "final_video.mp4"


def test_cache_reuse(tmp_path):
    storyboard, rendered = make_project(tmp_path)
    composer = VideoComposer(width=160, height=90, fps=5)
    first = composer.compose(storyboard, rendered, tmp_path, "compose-test")
    mtime = (tmp_path / "final_video.mp4").stat().st_mtime_ns
    second = composer.compose(storyboard, rendered, tmp_path, "compose-test")
    assert first.model_dump() == second.model_dump()
    assert (tmp_path / "final_video.mp4").stat().st_mtime_ns == mtime


def test_changed_scene_invalidates_composition(tmp_path):
    storyboard, rendered = make_project(tmp_path)
    composer = VideoComposer(width=160, height=90, fps=5)
    first = composer.compose(storyboard, rendered, tmp_path, "compose-test")
    rendered.scenes[0].fingerprint = "changed"
    second = composer.compose(storyboard, rendered, tmp_path, "compose-test")
    assert second.composition_fingerprint != first.composition_fingerprint


def test_failed_composition_preserves_valid_output(tmp_path, monkeypatch):
    storyboard, rendered = make_project(tmp_path)
    composer = VideoComposer(width=160, height=90, fps=5)
    first = composer.compose(storyboard, rendered, tmp_path, "compose-test")
    original = composer._ffmpeg_path
    monkeypatch.setattr(composer, "_ffmpeg_path", lambda: "/does/not/exist")
    rendered.scenes[0].fingerprint = "changed"
    with pytest.raises((RuntimeError, FileNotFoundError)):
        composer.compose(storyboard, rendered, tmp_path, "compose-test")
    assert (tmp_path / "final_video.mp4").exists()
    assert (tmp_path / "final_video.mp4").stat().st_size == first.file_size_bytes
    assert not (tmp_path / "final_video.tmp.mp4").exists()
    monkeypatch.setattr(composer, "_ffmpeg_path", original)


def test_graph_state_update(monkeypatch, tmp_path):
    storyboard, rendered = make_project(tmp_path)
    expected = VideoComposer(width=160, height=90, fps=5).compose(storyboard, rendered, tmp_path, "compose-test")

    class StubComposer:
        def compose(self, storyboard, rendered_scenes, project_dir, project_id):
            return expected

    monkeypatch.setattr("app.graph.workflow.VideoComposer", StubComposer)
    monkeypatch.chdir(tmp_path)
    state = VideoState(project_id="compose-test", topic="Demo", storyboard=storyboard, rendered_scenes=rendered)
    updated = node_compose_video(state)
    assert updated["final_video"] == expected
    assert updated["final_video_path"] == "final_video.mp4"
    assert updated["status"] == "completed"
