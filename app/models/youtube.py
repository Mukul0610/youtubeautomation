from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field, field_validator


class YouTubePrivacy(str, Enum):
    PRIVATE = "private"
    UNLISTED = "unlisted"
    PUBLIC = "public"


class YouTubeUploadRequest(BaseModel):
    project_id: str = Field(..., min_length=1)
    video_path: str = Field(..., min_length=1)
    thumbnail_path: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1, max_length=100)
    description: str = Field(..., max_length=5000)
    tags: list[str] = Field(default_factory=list)
    category_id: str = Field(default="27", min_length=1)
    privacy_status: YouTubePrivacy = YouTubePrivacy.PRIVATE
    channel_id: str | None = None

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, value):
        return list(dict.fromkeys(tag.strip() for tag in value if tag and tag.strip()))[:30]


class YouTubeUploadResult(BaseModel):
    project_id: str = Field(..., min_length=1)
    video_id: str = Field(..., min_length=1)
    video_url: str = Field(..., min_length=1)
    channel_id: str | None = None
    privacy_status: YouTubePrivacy
    upload_status: str = Field(..., min_length=1)
    thumbnail_uploaded: bool = False
    thumbnail_error: str | None = None
    published_at: datetime
    title: str = Field(..., min_length=1)
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    category_id: str = Field(..., min_length=1)
    is_mock: bool = False
