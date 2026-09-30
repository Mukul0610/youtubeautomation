from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class AudioScene(BaseModel):
    scene_id: str = Field(..., min_length=1)
    audio_path: str = Field(..., min_length=1)
    duration_seconds: float = Field(..., gt=0)
    word_count: int = Field(..., ge=1)
    start_time_seconds: float = Field(..., ge=0)
    end_time_seconds: float = Field(..., gt=0)

    @field_validator("end_time_seconds")
    @classmethod
    def end_after_start(cls, value: float, info):
        start = info.data.get("start_time_seconds", 0.0)
        if value <= start:
            raise ValueError("audio scene end must be after its start")
        return value


class TTSResult(BaseModel):
    project_id: str | None = None
    provider: str = Field(..., min_length=1)
    voice: str = Field(..., min_length=1)
    language: str = Field(default="en", min_length=1)
    format: str = Field(default="wav", min_length=1)
    sample_rate: int = Field(default=44_100, gt=0)
    total_duration_seconds: float = Field(..., ge=0)
    scenes: list[AudioScene] = Field(default_factory=list)

    @property
    def scene_count(self) -> int:
        return len(self.scenes)

    def model_post_init(self, __context):
        if self.scenes:
            final_end = self.scenes[-1].end_time_seconds
            if abs(self.total_duration_seconds - final_end) > 0.05:
                raise ValueError("total duration must match the final scene end time")
