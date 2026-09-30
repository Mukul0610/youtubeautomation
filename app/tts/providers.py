from __future__ import annotations

import base64
import wave
from abc import ABC, abstractmethod
from pathlib import Path

from pydantic import BaseModel, Field


class AudioResult(BaseModel):
    output_path: str
    duration_seconds: float = Field(..., gt=0)
    sample_rate: int = Field(..., gt=0)
    format: str = "wav"


class TTSProvider(ABC):
    name: str = "provider"

    @abstractmethod
    def synthesize(self, text: str, voice: str, output_path: Path) -> AudioResult:
        raise NotImplementedError


class MockTTSProvider(TTSProvider):
    """Deterministic mono PCM WAV provider for local development and tests."""

    name = "mock"
    sample_rate = 44_100
    words_per_minute = 140

    def synthesize(self, text: str, voice: str, output_path: Path) -> AudioResult:
        words = len(text.split())
        if words == 0:
            raise ValueError("mock TTS cannot synthesize empty text")
        duration = max(0.1, words / self.words_per_minute * 60)
        frame_count = round(duration * self.sample_rate)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(output_path), "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(self.sample_rate)
            audio.writeframes(b"\x00\x00" * frame_count)
        return AudioResult(
            output_path=str(output_path),
            duration_seconds=frame_count / self.sample_rate,
            sample_rate=self.sample_rate,
        )


class SarvamTTSProvider(TTSProvider):
    """Sarvam Bulbul TTS provider backed by the official ``sarvamai`` SDK."""

    name = "sarvam"
    sample_rate = 24_000

    def __init__(
        self,
        api_key: str,
        *,
        model: str = "bulbul:v3",
        language: str = "en-IN",
        speed: float = 1.0,
        client=None,
    ):
        if not api_key:
            raise ValueError("SARVAM_API_KEY is required for the Sarvam TTS provider")
        if not 0.5 <= speed <= 2.0:
            raise ValueError("Sarvam Bulbul v3 TTS speed must be between 0.5 and 2.0")
        if client is None:
            try:
                from sarvamai import SarvamAI
            except ImportError as exc:
                raise RuntimeError("sarvamai is required for the Sarvam TTS provider") from exc
            client = SarvamAI(api_subscription_key=api_key)
        self.client = client
        self.model = model
        self.language = language
        self.speed = speed

    def synthesize(self, text: str, voice: str, output_path: Path) -> AudioResult:
        if not text.strip():
            raise ValueError("Sarvam TTS cannot synthesize empty text")
        try:
            response = self.client.text_to_speech.convert(
                text=text,
                language_code=self.language,
                speaker=voice,
                pace=self.speed,
                model=self.model,
                output_audio_codec="wav",
            )
        except Exception as exc:
            raise RuntimeError(f"Sarvam TTS request failed: {exc}") from exc

        audios = getattr(response, "audios", None)
        if not audios or not audios[0]:
            raise RuntimeError("Sarvam TTS returned no audio data")
        try:
            audio_bytes = base64.b64decode(audios[0], validate=True)
        except (ValueError, TypeError) as exc:
            raise RuntimeError("Sarvam TTS returned invalid base64 audio") from exc
        if not audio_bytes:
            raise RuntimeError("Sarvam TTS returned empty audio data")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            output_path.write_bytes(audio_bytes)
        except OSError as exc:
            raise RuntimeError(f"Unable to write Sarvam audio to {output_path}") from exc
        duration, sample_rate = read_wav_duration(output_path)
        return AudioResult(
            output_path=str(output_path),
            duration_seconds=duration,
            sample_rate=sample_rate,
        )


def read_wav_duration(path: Path) -> tuple[float, int]:
    try:
        with wave.open(str(path), "rb") as audio:
            if audio.getnchannels() != 1 or audio.getsampwidth() != 2:
                raise ValueError("audio must be mono 16-bit PCM WAV")
            sample_rate = audio.getframerate()
            frames = audio.getnframes()
            if sample_rate <= 0 or frames <= 0:
                raise ValueError("audio contains no readable frames")
            return frames / sample_rate, sample_rate
    except (OSError, EOFError, wave.Error) as exc:
        raise ValueError(f"audio file is unreadable: {path}") from exc


def build_tts_provider(name: str = "mock", **kwargs) -> TTSProvider:
    if name.lower() == "mock":
        return MockTTSProvider()
    if name.lower() == "sarvam":
        return SarvamTTSProvider(**kwargs)
    raise ValueError(f"Unsupported TTS provider: {name}")
