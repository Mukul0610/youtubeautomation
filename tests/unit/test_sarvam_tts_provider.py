import base64
import wave

import pytest

from app.agents.tts_agent import TTSAgent
from app.config import settings
from app.tts.providers import MockTTSProvider, SarvamTTSProvider, build_tts_provider


class FakeSarvamResponse:
    def __init__(self, audios):
        self.audios = audios


class FakeTTSClient:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    class TextToSpeech:
        def __init__(self, parent):
            self.parent = parent

        def convert(self, **kwargs):
            self.parent.calls.append(kwargs)
            if self.parent.error:
                raise self.parent.error
            return self.parent.response

    @property
    def text_to_speech(self):
        return self.TextToSpeech(self)


def wav_base64(tmp_path):
    path = tmp_path / "source.wav"
    MockTTSProvider().synthesize("hello world", "default", path)
    return base64.b64encode(path.read_bytes()).decode()


def test_sarvam_provider_requires_api_key():
    with pytest.raises(ValueError, match="SARVAM_API_KEY"):
        SarvamTTSProvider("")


def test_sarvam_provider_initializes_with_configuration(tmp_path):
    client = FakeTTSClient(FakeSarvamResponse([wav_base64(tmp_path)]))
    provider = SarvamTTSProvider(
        "test-key",
        model="bulbul:v3",
        language="en-IN",
        speed=1.1,
        client=client,
    )
    output = tmp_path / "scene.wav"
    provider.synthesize("hello world", "anushka", output)
    call = client.calls[0]
    assert call["model"] == "bulbul:v3"
    assert call["language_code"] == "en-IN"
    assert call["speaker"] == "anushka"
    assert call["pace"] == 1.1
    assert call["output_audio_codec"] == "wav"
    assert output.exists()


def test_sarvam_provider_decodes_audio_and_returns_metadata(tmp_path):
    client = FakeTTSClient(FakeSarvamResponse([wav_base64(tmp_path)]))
    output = tmp_path / "scene.wav"
    result = SarvamTTSProvider("test-key", client=client).synthesize("hello world", "anushka", output)
    assert result.format == "wav"
    assert result.duration_seconds > 0
    with wave.open(str(output), "rb") as audio:
        assert audio.getnframes() > 0


def test_sarvam_provider_rejects_empty_response(tmp_path):
    client = FakeTTSClient(FakeSarvamResponse([]))
    with pytest.raises(RuntimeError, match="no audio data"):
        SarvamTTSProvider("test-key", client=client).synthesize("hello", "anushka", tmp_path / "scene.wav")


def test_sarvam_provider_rejects_invalid_audio(tmp_path):
    client = FakeTTSClient(FakeSarvamResponse([base64.b64encode(b"bad").decode()]))
    with pytest.raises(ValueError, match="audio file is unreadable"):
        SarvamTTSProvider("test-key", client=client).synthesize("hello", "anushka", tmp_path / "scene.wav")


def test_sarvam_provider_wraps_api_errors(tmp_path):
    client = FakeTTSClient(error=RuntimeError("unauthorized"))
    with pytest.raises(RuntimeError, match="Sarvam TTS request failed"):
        SarvamTTSProvider("test-key", client=client).synthesize("hello", "anushka", tmp_path / "scene.wav")


def test_factory_selects_sarvam(monkeypatch):
    monkeypatch.setattr(settings, "sarvam_api_key", "test-key")
    provider = build_tts_provider("sarvam", api_key="test-key", client=FakeTTSClient())
    assert isinstance(provider, SarvamTTSProvider)


def test_factory_keeps_mock_provider():
    assert isinstance(build_tts_provider("mock"), MockTTSProvider)


def test_tts_agent_uses_sarvam_configuration(monkeypatch):
    monkeypatch.setattr(settings, "tts_provider", "sarvam")
    monkeypatch.setattr(settings, "sarvam_api_key", "test-key")
    monkeypatch.setattr(settings, "tts_model", "bulbul:v3")
    monkeypatch.setattr(settings, "tts_language", "en-IN")
    monkeypatch.setattr(settings, "tts_voice", "anushka")
    monkeypatch.setattr(settings, "tts_speed", 1.0)
    monkeypatch.setattr("app.agents.tts_agent.build_tts_provider", lambda name, **kwargs: SarvamTTSProvider("test-key", client=FakeTTSClient()))
    agent = TTSAgent()
    assert isinstance(agent.provider, SarvamTTSProvider)
    assert agent.voice == "anushka"
    assert agent.language == "en-IN"
