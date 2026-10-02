from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class AnalyticsStatus(str, Enum):
    PENDING = "pending"
    AVAILABLE = "available"
    PARTIAL = "partial"
    FAILED = "failed"


class AnalyticsRequest(BaseModel):
    project_id: str = Field(..., min_length=1)
    video_id: str = Field(..., min_length=1)
    channel_id: str | None = None
    lookback_days: int = Field(default=30, ge=1)


class AnalyticsSnapshot(BaseModel):
    collected_at: datetime
    fingerprint: str = Field(..., min_length=1)
    status: AnalyticsStatus = AnalyticsStatus.AVAILABLE
    views: int | None = Field(default=None, ge=0)
    watch_time_minutes: float | None = Field(default=None, ge=0)
    average_view_duration_seconds: float | None = Field(default=None, ge=0)
    average_view_percentage: float | None = Field(default=None, ge=0, le=100)
    likes: int | None = Field(default=None, ge=0)
    comments: int | None = Field(default=None, ge=0)
    shares: int | None = Field(default=None, ge=0)
    subscribers_gained: int | None = Field(default=None, ge=0)
    subscribers_lost: int | None = Field(default=None, ge=0)
    impressions: int | None = Field(default=None, ge=0)
    impressions_click_through_rate: float | None = Field(default=None, ge=0, le=100)
    published_at: datetime | None = None
    video_age_days: int | None = Field(default=None, ge=0)
    is_mock: bool = False


class AnalyticsHistory(BaseModel):
    project_id: str = Field(..., min_length=1)
    video_id: str = Field(..., min_length=1)
    channel_id: str | None = None
    snapshots: list[AnalyticsSnapshot] = Field(default_factory=list)


class VideoContentFeatures(BaseModel):
    topic: str
    duration_seconds: float | None = None
    script_word_count: int | None = None
    scene_count: int | None = None
    thumbnail_template: str | None = None
    thumbnail_text_length: int | None = None
    title_length: int | None = None
    title_keywords: list[str] = Field(default_factory=list)
    asset_count: int | None = None


class GrowthMetrics(BaseModel):
    view_growth: int | None = None
    view_growth_rate: float | None = None
    watch_time_growth_minutes: float | None = None


class EngagementMetrics(BaseModel):
    like_rate: float | None = None
    comment_rate: float | None = None
    share_rate: float | None = None
    subscriber_conversion_rate: float | None = None


class RetentionMetrics(BaseModel):
    average_view_duration_seconds: float | None = None
    average_view_percentage: float | None = None


class ReachMetrics(BaseModel):
    impressions: int | None = None
    impressions_click_through_rate: float | None = None


class VideoPerformanceAnalysis(BaseModel):
    project_id: str
    video_id: str
    analysis_timestamp: datetime
    sample_size: int = Field(..., ge=1)
    content_features: VideoContentFeatures | None = None
    growth_metrics: GrowthMetrics
    engagement_metrics: EngagementMetrics
    retention_metrics: RetentionMetrics
    reach_metrics: ReachMetrics
    view_trend: str = "insufficient_data"
    engagement_trend: str = "insufficient_data"
    retention_trend: str = "insufficient_data"
    observations: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)


class FeedbackReport(BaseModel):
    project_id: str
    video_id: str
    generated_at: datetime
    sample_size: int = Field(..., ge=1)
    sample_strength: str
    what_performed_well: list[str] = Field(default_factory=list)
    potential_issues: list[str] = Field(default_factory=list)
    observations: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    supporting_metrics: dict[str, float | int | str | None] = Field(default_factory=dict)
