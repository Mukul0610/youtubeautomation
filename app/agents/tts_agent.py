from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.config import settings
from app.models.storyboard import Storyboard
from app.models.tts import AudioScene, TTSResult
from app.tts.providers import TTSProvider, build_tts_provider, read_wav_duration

logger = logging.getLogger(__name__)


class TTSAgent:
    """Synthesize storyboard narration into scene-level audio and a timeline."""

    def __init__(
        self,
        provider: TTSProvider | None = None,
        *,
        voice: str | None = None,
        language: str | None = None,
        max_retries: int = 3,
    ):
        provider_name = settings.tts_provider or "mock"
        self.provider = provider or build_tts_provider(
            provider_name,
            api_key=settings.sarvam_api_key,
            model=settings.tts_model or "bulbul:v3",
            language=settings.tts_language,
            speed=settings.tts_speed,
        )
        self.voice = voice or settings.tts_voice or "default"
        self.language = language or settings.tts_language
        self.max_retries = max_retries

    def synthesize(
        self,
        storyboard: Storyboard,
        *,
        project_id: str | None = None,
        project_dir: str | Path | None = None,
    ) -> TTSResult:
        if storyboard is None or not storyboard.scenes:
            raise ValueError("TTS requires a storyboard with at least one scene.")
        if project_dir is None:
            raise ValueError("TTS requires a project directory for audio output.")

        directory = Path(project_dir)
        cached = self._load_valid_cache(directory, storyboard, project_id)
        if cached is not None:
            logger.info("[TTS] Using cached metadata")
            return cached

        audio_dir = directory / "audio"
        audio_dir.mkdir(parents=True, exist_ok=True)
        audio_scenes: list[AudioScene] = []
        start_time = 0.0
        for scene in storyboard.scenes:
            if not scene.narration.strip():
                raise ValueError(f"TTS scene {scene.id} has empty narration.")
            scene_id = str(scene.id)
            audio_path = audio_dir / f"{scene_id}.wav"
            audio_result = self._ensure_scene_audio(scene.narration, audio_path)
            duration, sample_rate = read_wav_duration(audio_path)
            expected = len(scene.narration.split()) / 140 * 60
            if abs(duration - expected) > max(1.0, expected * 0.25):
                raise ValueError(
                    f"TTS scene {scene_id} duration {duration:.2f}s differs from "
                    f"narration estimate {expected:.2f}s"
                )
            end_time = start_time + duration
            audio_scenes.append(AudioScene(
                scene_id=scene_id,
                audio_path=str(audio_path.relative_to(directory)),
                duration_seconds=duration,
                word_count=len(scene.narration.split()),
                start_time_seconds=start_time,
                end_time_seconds=end_time,
            ))
            start_time = end_time
            logger.info("[TTS] Scene %s duration %.2fs", scene_id, duration)

        result = TTSResult(
            project_id=project_id,
            provider=self.provider.name,
            voice=self.voice,
            language=self.language,
            sample_rate=sample_rate,
            total_duration_seconds=start_time,
            scenes=audio_scenes,
        )
        self.persist_result(result, directory)
        return result

    def _ensure_scene_audio(self, narration: str, output_path: Path):
        if output_path.exists():
            try:
                read_wav_duration(output_path)
                return None
            except ValueError:
                output_path.unlink(missing_ok=True)

        last_error: Exception | None = None
        for _ in range(self.max_retries):
            try:
                result = self.provider.synthesize(narration, self.voice, output_path)
                read_wav_duration(output_path)
                return result
            except Exception as exc:
                last_error = exc
        raise RuntimeError(
            f"TTS provider {self.provider.name} failed for {output_path.name} "
            f"after {self.max_retries} attempts: {last_error}"
        ) from last_error

    def _load_valid_cache(
        self,
        project_dir: Path,
        storyboard: Storyboard,
        project_id: str | None,
    ) -> TTSResult | None:
        path = project_dir / "tts.json"
        if not path.exists():
            return None
        try:
            result = TTSResult.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, ValidationError):
            return None
        if result.project_id != project_id or len(result.scenes) != len(storyboard.scenes):
            return None
        expected_ids = [str(scene.id) for scene in storyboard.scenes]
        if [scene.scene_id for scene in result.scenes] != expected_ids:
            return None
        for audio_scene in result.scenes:
            audio_path = project_dir / audio_scene.audio_path
            try:
                duration, _ = read_wav_duration(audio_path)
            except ValueError:
                return None
            if abs(duration - audio_scene.duration_seconds) > 0.05:
                return None
        return result

    @staticmethod
    def persist_result(result: TTSResult, project_dir: str | Path) -> Path:
        path = Path(project_dir) / "tts.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
        return path

    @staticmethod
    def load_result(project_dir: str | Path) -> TTSResult | None:
        path = Path(project_dir) / "tts.json"
        if not path.exists():
            return None
        try:
            return TTSResult.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, ValidationError):
            return None
