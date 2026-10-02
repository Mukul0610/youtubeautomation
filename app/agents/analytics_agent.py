from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError

from app.analytics.providers import AnalyticsProvider, build_analytics_provider
from app.config import settings
from app.models.analytics import (
    AnalyticsHistory, AnalyticsRequest, AnalyticsSnapshot, AnalyticsStatus,
    EngagementMetrics, FeedbackReport, GrowthMetrics,
    ReachMetrics, RetentionMetrics, VideoContentFeatures, VideoPerformanceAnalysis,
)
from app.models.script import Script
from app.models.thumbnail import ThumbnailResult
from app.models.youtube import YouTubeUploadResult


class AnalyticsAgent:
    """Collect raw analytics and derive conservative, measurable feedback."""

    def __init__(self, provider: AnalyticsProvider | None = None):
        self.provider = provider or build_analytics_provider()

    def collect(self, publication: YouTubeUploadResult, project_dir: str | Path) -> AnalyticsHistory:
        if not publication or not publication.video_id:
            raise ValueError("analytics collection requires a YouTube publication")
        directory = Path(project_dir)
        history_path = directory / "analytics.json"
        history = self.load_history(directory) or AnalyticsHistory(
            project_id=publication.project_id, video_id=publication.video_id, channel_id=publication.channel_id
        )
        snapshot = self.provider.get_video_analytics(AnalyticsRequest(
            project_id=publication.project_id,
            video_id=publication.video_id,
            channel_id=publication.channel_id,
            lookback_days=settings.analytics_lookback_days,
        ))
        if not any(item.fingerprint == snapshot.fingerprint for item in history.snapshots):
            history.snapshots.append(snapshot)
        history_path.parent.mkdir(parents=True, exist_ok=True)
        history_path.write_text(history.model_dump_json(indent=2), encoding="utf-8")
        return history

    def analyze(
        self,
        history: AnalyticsHistory,
        *,
        topic: str,
        script: Script | None = None,
        thumbnail: ThumbnailResult | None = None,
        duration_seconds: float | None = None,
        scene_count: int | None = None,
        asset_count: int | None = None,
        project_dir: str | Path | None = None,
    ) -> tuple[VideoPerformanceAnalysis, FeedbackReport]:
        if not history.snapshots:
            raise ValueError("analytics analysis requires at least one snapshot")
        current = history.snapshots[-1]
        previous = history.snapshots[-2] if len(history.snapshots) > 1 else None
        features = VideoContentFeatures(
            topic=topic,
            duration_seconds=duration_seconds,
            script_word_count=script.estimated_word_count if script else None,
            scene_count=scene_count,
            thumbnail_template=thumbnail.template_id if thumbnail else None,
            thumbnail_text_length=len(thumbnail.title_text) if thumbnail else None,
            title_length=len(script.title) if script else None,
            title_keywords=[word.lower() for word in topic.split() if len(word) > 2][:10],
            asset_count=asset_count,
        )
        growth = GrowthMetrics(
            view_growth=self._delta(current.views, previous.views if previous else None),
            view_growth_rate=self._rate(current.views, previous.views if previous else None),
            watch_time_growth_minutes=self._delta_float(current.watch_time_minutes, previous.watch_time_minutes if previous else None),
        )
        engagement = EngagementMetrics(
            like_rate=self._rate(current.likes, current.views),
            comment_rate=self._rate(current.comments, current.views),
            share_rate=self._rate(current.shares, current.views),
            subscriber_conversion_rate=self._rate(current.subscribers_gained, current.views),
        )
        retention = RetentionMetrics(
            average_view_duration_seconds=current.average_view_duration_seconds,
            average_view_percentage=current.average_view_percentage,
        )
        reach = ReachMetrics(impressions=current.impressions, impressions_click_through_rate=current.impressions_click_through_rate)
        observations: list[str] = []
        recommendations: list[str] = []
        if current.views is None:
            observations.append("Views are unavailable; performance cannot yet be evaluated.")
        if engagement.like_rate is not None:
            observations.append(f"Observed like rate is {engagement.like_rate:.2f}% of views.")
        if retention.average_view_percentage is not None:
            observations.append(f"Observed average percentage viewed is {retention.average_view_percentage:.2f}%.")
        if previous is not None and growth.view_growth is not None:
            trend = "increasing" if growth.view_growth > 0 else "decreasing" if growth.view_growth < 0 else "stable"
        else:
            trend = "insufficient_data"
        if retention.average_view_percentage is not None and retention.average_view_percentage < 40:
            recommendations.append("Test a shorter introduction or stronger opening hook; lower retention may indicate early drop-off.")
        if current.impressions_click_through_rate is not None and current.impressions_click_through_rate < 4:
            recommendations.append("Test a clearer thumbnail composition and shorter headline; the observed CTR is worth improving.")
        if not recommendations:
            recommendations.append("Continue collecting snapshots before changing content strategy; the current sample is observational.")
        analysis = VideoPerformanceAnalysis(
            project_id=history.project_id, video_id=history.video_id, analysis_timestamp=datetime.now(timezone.utc),
            sample_size=len(history.snapshots), content_features=features, growth_metrics=growth,
            engagement_metrics=engagement, retention_metrics=retention, reach_metrics=reach,
            view_trend=trend, observations=observations, recommendations=recommendations,
        )
        strength = "insufficient sample size" if len(history.snapshots) == 1 else "weak signal" if len(history.snapshots) < 5 else "potential pattern" if len(history.snapshots) < 10 else "stronger observational signal"
        feedback = FeedbackReport(
            project_id=history.project_id, video_id=history.video_id, generated_at=datetime.now(timezone.utc),
            sample_size=len(history.snapshots), sample_strength=strength,
            what_performed_well=[observation for observation in observations if "rate" in observation.lower()],
            potential_issues=[recommendation for recommendation in recommendations if "lower" in recommendation or "CTR" in recommendation],
            observations=observations, recommendations=recommendations,
            supporting_metrics={"views": current.views, "like_rate": engagement.like_rate, "average_view_percentage": retention.average_view_percentage, "ctr": reach.impressions_click_through_rate},
        )
        if project_dir is not None:
            directory = Path(project_dir)
            (directory / "performance_analysis.json").write_text(analysis.model_dump_json(indent=2), encoding="utf-8")
            (directory / "feedback.json").write_text(feedback.model_dump_json(indent=2), encoding="utf-8")
        return analysis, feedback

    @staticmethod
    def load_history(project_dir: str | Path) -> AnalyticsHistory | None:
        path = Path(project_dir) / "analytics.json"
        if not path.exists():
            return None
        try:
            return AnalyticsHistory.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, ValidationError):
            return None

    @staticmethod
    def _delta(current, previous):
        return current - previous if current is not None and previous is not None else None

    @staticmethod
    def _delta_float(current, previous):
        return current - previous if current is not None and previous is not None else None

    @staticmethod
    def _rate(numerator, denominator):
        if numerator is None or denominator in (None, 0):
            return None
        return round(numerator / denominator * 100, 6)
