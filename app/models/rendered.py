from __future__ import annotations

from pydantic import BaseModel, Field


class RenderedScene(BaseModel):
    scene_id: str = Field(..., min_length=1)
    video_path: str = Field(..., min_length=1)
    duration_seconds: float = Field(..., gt=0)
    width: int = Field(..., gt=0)
    height: int = Field(..., gt=0)
    fps: int = Field(..., gt=0)
    audio_path: str = Field(..., min_length=1)
    fingerprint: str = Field(..., min_length=1)
    claim_ids: list[str] = Field(default_factory=list)


class RenderedScenes(BaseModel):
    project_id: str | None = None
    scenes: list[RenderedScene] = Field(default_factory=list)
