from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ThumbnailRequest(BaseModel):
    project_id: str | None = None
    topic: str = Field(..., min_length=1)
    title_text: str = Field(..., min_length=1)
    subtitle_text: str | None = None
    asset_ids: list[str] = Field(default_factory=list)
    asset_paths: list[str] = Field(default_factory=list)
    template_id: str = Field(default="finance_explainer", min_length=1)
    output_path: str = Field(..., min_length=1)
    width: int = Field(default=1280, gt=0)
    height: int = Field(default=720, gt=0)


class ThumbnailResult(BaseModel):
    project_id: str | None = None
    thumbnail_path: str = Field(..., min_length=1)
    width: int = Field(..., gt=0)
    height: int = Field(..., gt=0)
    format: str = Field(default="PNG", min_length=1)
    title_text: str = Field(..., min_length=1)
    subtitle_text: str | None = None
    asset_ids: list[str] = Field(default_factory=list)
    template_id: str = Field(..., min_length=1)
    fingerprint: str = Field(..., min_length=1)
    created_at: datetime
