import wave

import pytest

from app.agents.tts_agent import TTSAgent
from app.graph.state import VideoState
from app.graph.workflow import node_tts
from app.models.storyboard import Storyboard, StoryboardScene
from app.models.tts import TTSResult
from app.tts.providers import MockTTSProvider, TTSProvider


class CountingProvider(MockTTSProvider):
    def __init__(self, failures=0):
        self.calls = []
        self.failures = failures

    def synthesize(self, text, voice, output_path):
        self.calls.append(output_path.name)
        if self.failures:
            self.failures -= 1
            raise RuntimeError("provider failure")
        return super().synthesize(text, voice, output_path)


class AlwaysFailProvider(TTSProvider):
    name = "failing"

    def synthesize(self, text, voice, output_path):
        raise RuntimeError("provider unavailable")


def make_storyboard():
    return Storyboard(scenes=[
        StoryboardScene(id="scene_001", duration_seconds=5, narration="Imagine you buy something from a local store.", visual_description="Customer taps a card.", background="store"),
        StoryboardScene(id="scene_002", duration_seconds=5, narration="The payment travels through several systems.", visual_description="Arrows connect banks.", background="network"),
        StoryboardScene(id="scene_003", duration_seconds=5, narration="Each participant can earn revenue from the transaction.", visual_description="A simple revenue diagram builds.", background="office"),
    ])


def test_mock_provider_generates_valid_audio_without_key(tmp_path):
    provider = MockTTSProvider()
    result = provider.synthesize("A short narration.", "default", tmp_path / "scene.wav")
    assert result.output_path.endswith("scene.wav")
    with wave.open(result.output_path, "rb") as audio:
        assert audio.getnchannels() == 1
        assert audio.getsampwidth() == 2
        assert audio.getnframes() > 0


def test_valid_tts_generation_and_multiple_scene_audio(tmp_path):
    result = TTSAgent(provider=MockTTSProvider()).synthesize(make_storyboard(), project_id="demo", project_dir=tmp_path)
    assert len(result.scenes) == 3
    assert all((tmp_path / scene.audio_path).exists() for scene in result.scenes)
    assert result.total_duration_seconds == result.scenes[-1].end_time_seconds


def test_audio_duration_metadata_and_timeline(tmp_path):
    result = TTSAgent(provider=MockTTSProvider()).synthesize(make_storyboard(), project_id="demo", project_dir=tmp_path)
    assert result.scenes[0].start_time_seconds == 0
    assert result.scenes[1].start_time_seconds == result.scenes[0].end_time_seconds
    assert result.scenes[2].end_time_seconds == result.total_duration_seconds
    assert all(scene.duration_seconds > 0 for scene in result.scenes)


def test_tts_json_is_persisted_and_valid(tmp_path):
    TTSAgent(provider=MockTTSProvider()).synthesize(make_storyboard(), project_id="demo", project_dir=tmp_path)
    parsed = TTSResult.model_validate_json((tmp_path / "tts.json").read_text())
    assert parsed.provider == "mock"
    assert parsed.scene_count == 3


def test_empty_narration_is_rejected(tmp_path):
    storyboard = make_storyboard()
    storyboard.scenes[1].narration = "   "
    with pytest.raises(ValueError, match="empty narration"):
        TTSAgent(provider=MockTTSProvider()).synthesize(storyboard, project_id="demo", project_dir=tmp_path)


def test_missing_storyboard_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="storyboard"):
        TTSAgent(provider=MockTTSProvider()).synthesize(None, project_id="demo", project_dir=tmp_path)


def test_provider_failure_retries(tmp_path):
    provider = CountingProvider(failures=2)
    result = TTSAgent(provider=provider).synthesize(make_storyboard(), project_id="demo", project_dir=tmp_path)
    assert result.scene_count == 3
    assert provider.calls[:3] == ["scene_001.wav", "scene_001.wav", "scene_001.wav"]


def test_retry_exhaustion_raises(tmp_path):
    with pytest.raises(RuntimeError, match="failed for scene_001.wav"):
        TTSAgent(provider=AlwaysFailProvider(), max_retries=2).synthesize(make_storyboard(), project_id="demo", project_dir=tmp_path)


def test_valid_cache_is_reused(tmp_path):
    provider = CountingProvider()
    agent = TTSAgent(provider=provider)
    first = agent.synthesize(make_storyboard(), project_id="demo", project_dir=tmp_path)
    provider.calls.clear()
    second = agent.synthesize(make_storyboard(), project_id="demo", project_dir=tmp_path)
    assert first.model_dump() == second.model_dump()
    assert provider.calls == []


def test_missing_audio_regenerates_only_affected_scene(tmp_path):
    provider = CountingProvider()
    agent = TTSAgent(provider=provider)
    agent.synthesize(make_storyboard(), project_id="demo", project_dir=tmp_path)
    provider.calls.clear()
    (tmp_path / "audio" / "scene_002.wav").unlink()
    result = agent.synthesize(make_storyboard(), project_id="demo", project_dir=tmp_path)
    assert result.scene_count == 3
    assert provider.calls == ["scene_002.wav"]


def test_corrupt_audio_regenerates_only_affected_scene(tmp_path):
    provider = CountingProvider()
    agent = TTSAgent(provider=provider)
    agent.synthesize(make_storyboard(), project_id="demo", project_dir=tmp_path)
    provider.calls.clear()
    (tmp_path / "audio" / "scene_003.wav").write_bytes(b"corrupt")
    agent.synthesize(make_storyboard(), project_id="demo", project_dir=tmp_path)
    assert provider.calls == ["scene_003.wav"]


def test_provider_abstraction_accepts_custom_provider(tmp_path):
    provider = CountingProvider()
    result = TTSAgent(provider=provider, voice="narrator").synthesize(make_storyboard(), project_id="demo", project_dir=tmp_path)
    assert result.provider == "mock"
    assert result.voice == "narrator"


def test_langgraph_state_receives_tts_result(monkeypatch, tmp_path):
    storyboard = make_storyboard()
    expected = TTSAgent(provider=MockTTSProvider()).synthesize(storyboard, project_id="demo", project_dir=tmp_path)

    class StubAgent:
        def synthesize(self, storyboard, *, project_id, project_dir):
            return expected

    monkeypatch.setattr("app.graph.workflow.TTSAgent", StubAgent)
    monkeypatch.chdir(tmp_path)
    state = VideoState(project_id="demo", topic="Demo", storyboard=storyboard)
    updated = node_tts(state)
    assert updated["tts_result"] == expected
    assert updated["errors"] == []
