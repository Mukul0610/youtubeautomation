from __future__ import annotations

from pydantic import BaseModel, Field


class VideoProject(BaseModel):
    project_id: str = Field(..., min_length=1)
    topic: str = Field(..., min_length=1)
    output_path: str | None = None
