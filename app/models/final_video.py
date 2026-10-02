from __future__ import annotations

from pydantic import BaseModel, Field


class FinalVideo(BaseModel):
    project_id: str | None = None
    video_path: str = Field(..., min_length=1)
    duration_seconds: float = Field(..., gt=0)
    width: int = Field(..., gt=0)
    height: int = Field(..., gt=0)
    fps: int = Field(..., gt=0)
    scene_count: int = Field(..., gt=0)
    file_size_bytes: int = Field(..., gt=0)
    composition_fingerprint: str = Field(..., min_length=1)
    scene_ids: list[str] = Field(default_factory=list)
