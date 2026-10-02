from pathlib import Path

import pytest
from PIL import Image

from app.agents.youtube_publisher import YouTubePublisher
from app.config import settings
from app.graph.state import VideoState
from app.graph.workflow import node_youtube_publish
from app.models.final_video import FinalVideo
from app.models.script import Script
from app.models.thumbnail import ThumbnailResult
from app.models.youtube import YouTubePrivacy, YouTubeUploadRequest, YouTubeUploadResult
from app.youtube.providers import MockYouTubeProvider, YouTubeProvider, build_youtube_provider


def make_inputs(tmp_path):
    video = tmp_path / "final_video.mp4"
    video.write_bytes(b"valid video placeholder")
    thumb = tmp_path / "thumbnail.png"
    Image.new("RGB", (1280, 720), "blue").save(thumb)
    final = FinalVideo(project_id="yt-test", video_path="final_video.mp4", duration_seconds=5, width=1280, height=720, fps=30, scene_count=1, file_size_bytes=video.stat().st_size, composition_fingerprint="fp", scene_ids=["scene_001"])
    thumbnail = ThumbnailResult(project_id="yt-test", thumbnail_path="thumbnail.png", width=1280, height=720, format="PNG", title_text="HOW VISA MAKES MONEY", asset_ids=[], template_id="finance_explainer", fingerprint="thumb-fp", created_at="2026-10-02T00:00:00Z")
    return final, thumbnail


def test_metadata_generation_and_mock_upload(tmp_path, monkeypatch):
    final, thumbnail = make_inputs(tmp_path)
    monkeypatch.setattr(settings, "youtube_default_privacy", "private")
    result = YouTubePublisher(provider=MockYouTubeProvider()).publish("yt-test", "How Visa Makes Money", final, thumbnail, project_dir=tmp_path)
    assert result.video_id == "mock-yt-test"
    assert result.is_mock is True
    assert result.privacy_status == YouTubePrivacy.PRIVATE
    assert "finance" in result.tags
    assert (tmp_path / "youtube.json").exists()


def test_privacy_modes_are_passed(monkeypatch, tmp_path):
    final, thumbnail = make_inputs(tmp_path)
    monkeypatch.setattr(settings, "youtube_default_privacy", "unlisted")
    result = YouTubePublisher(provider=MockYouTubeProvider()).publish("yt-test", "Visa business model", final, thumbnail, project_dir=tmp_path)
    assert result.privacy_status == YouTubePrivacy.UNLISTED


def test_idempotency_avoids_duplicate_upload(tmp_path):
    final, thumbnail = make_inputs(tmp_path)
    publisher = YouTubePublisher(provider=MockYouTubeProvider())
    first = publisher.publish("yt-test", "Visa business model", final, thumbnail, project_dir=tmp_path)
    second = publisher.publish("yt-test", "Visa business model", final, thumbnail, project_dir=tmp_path)
    assert first.model_dump() == second.model_dump()


def test_force_republish_is_explicit(tmp_path):
    final, thumbnail = make_inputs(tmp_path)
    publisher = YouTubePublisher(provider=MockYouTubeProvider())
    first = publisher.publish("yt-test", "Visa business model", final, thumbnail, project_dir=tmp_path)
    second = publisher.publish("yt-test", "Visa business model", final, thumbnail, project_dir=tmp_path, force_republish=True)
    assert second.video_id == first.video_id


def test_missing_video_or_thumbnail_fails(tmp_path):
    final, thumbnail = make_inputs(tmp_path)
    (tmp_path / "final_video.mp4").unlink()
    with pytest.raises(ValueError, match="video is missing"):
        YouTubePublisher(provider=MockYouTubeProvider()).publish("yt-test", "Visa", final, thumbnail, project_dir=tmp_path)


def test_thumbnail_failure_preserves_video_id_and_does_not_reupload(tmp_path):
    final, thumbnail = make_inputs(tmp_path)

    class Provider(YouTubeProvider):
        name = "mock-failure"
        uploads = 0
        thumbnail_attempts = 0
        def upload_video(self, request):
            self.uploads += 1
            return YouTubeUploadResult(project_id=request.project_id, video_id="real-ish-id", video_url="https://example.invalid/real-ish-id", privacy_status=request.privacy_status, upload_status="uploaded", thumbnail_uploaded=False, thumbnail_error="initial failure", published_at="2026-10-02T00:00:00Z", title=request.title, description=request.description, tags=request.tags, category_id=request.category_id)
        def upload_thumbnail(self, video_id, thumbnail_path):
            self.thumbnail_attempts += 1
            raise RuntimeError("still unavailable")

    provider = Provider()
    result = YouTubePublisher(provider=provider).publish("yt-test", "Visa", final, thumbnail, project_dir=tmp_path)
    assert result.video_id == "real-ish-id"
    assert result.thumbnail_uploaded is False
    assert provider.uploads == 1
    assert provider.thumbnail_attempts == 1


def test_factory_selects_mock():
    assert isinstance(build_youtube_provider("mock"), MockYouTubeProvider)


def test_graph_state_update(monkeypatch, tmp_path):
    final, thumbnail = make_inputs(tmp_path)
    expected = YouTubePublisher(provider=MockYouTubeProvider()).publish("yt-test", "Visa", final, thumbnail, project_dir=tmp_path)

    class StubPublisher:
        def publish(self, project_id, topic, final_video, thumbnail, *, script, project_dir):
            return expected

    monkeypatch.setattr("app.graph.workflow.YouTubePublisher", StubPublisher)
    monkeypatch.chdir(tmp_path)
    state = VideoState(project_id="yt-test", topic="Visa", final_video=final, thumbnail=thumbnail)
    updated = node_youtube_publish(state)
    assert updated["youtube_publication"] == expected
    assert updated["status"] == "completed"
