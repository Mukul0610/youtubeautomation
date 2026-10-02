from datetime import datetime, timezone

import pytest

from app.agents.analytics_agent import AnalyticsAgent
from app.analytics.providers import MockAnalyticsProvider
from app.graph.state import VideoState
from app.graph.workflow import node_analytics, node_feedback
from app.models.analytics import AnalyticsHistory, AnalyticsSnapshot
from app.models.thumbnail import ThumbnailResult
from app.models.youtube import YouTubePrivacy, YouTubeUploadResult


def publication():
    return YouTubeUploadResult(
        project_id="analytics-test", video_id="video-1", video_url="https://example.invalid/video-1",
        privacy_status=YouTubePrivacy.PRIVATE, upload_status="uploaded", thumbnail_uploaded=True,
        published_at="2026-10-02T00:00:00Z", title="Visa", category_id="27",
    )


def snapshot(fingerprint, views=1000, likes=80):
    return AnalyticsSnapshot(
        collected_at=datetime(2026, 10, 2, tzinfo=timezone.utc), fingerprint=fingerprint,
        views=views, watch_time_minutes=2800, average_view_duration_seconds=168,
        average_view_percentage=62, likes=likes, comments=20, shares=10,
        subscribers_gained=25, subscribers_lost=1, impressions=12000,
        impressions_click_through_rate=8.3, is_mock=True,
    )


def test_mock_collection_persists_raw_analytics(tmp_path):
    history = AnalyticsAgent(provider=MockAnalyticsProvider(snapshot("snap-1"))).collect(publication(), tmp_path)
    assert history.snapshots[0].views == 1000
    assert (tmp_path / "analytics.json").exists()


def test_repeated_same_snapshot_is_idempotent(tmp_path):
    agent = AnalyticsAgent(provider=MockAnalyticsProvider(snapshot("same")))
    first = agent.collect(publication(), tmp_path)
    second = agent.collect(publication(), tmp_path)
    assert len(first.snapshots) == 1
    assert len(second.snapshots) == 1


def test_historical_snapshots_are_preserved(tmp_path):
    first = AnalyticsAgent(provider=MockAnalyticsProvider(snapshot("one", views=100))).collect(publication(), tmp_path)
    second = AnalyticsAgent(provider=MockAnalyticsProvider(snapshot("two", views=250))).collect(publication(), tmp_path)
    assert [item.views for item in second.snapshots] == [100, 250]


def test_derived_metrics_and_zero_denominators(tmp_path):
    history = AnalyticsHistory(project_id="analytics-test", video_id="video-1", snapshots=[snapshot("one", views=100), snapshot("two", views=200, likes=10)])
    analysis, feedback = AnalyticsAgent(provider=MockAnalyticsProvider()).analyze(history, topic="Visa", project_dir=tmp_path)
    assert analysis.growth_metrics.view_growth == 100
    assert analysis.growth_metrics.view_growth_rate == 100
    assert analysis.engagement_metrics.like_rate == 5
    zero = AnalyticsHistory(project_id="x", video_id="y", snapshots=[snapshot("z", views=0, likes=0)])
    zero_analysis, _ = AnalyticsAgent().analyze(zero, topic="x")
    assert zero_analysis.engagement_metrics.like_rate is None


def test_sample_size_protection_and_feedback_metrics(tmp_path):
    history = AnalyticsHistory(project_id="analytics-test", video_id="video-1", snapshots=[snapshot("one")])
    analysis, feedback = AnalyticsAgent().analyze(history, topic="Visa", project_dir=tmp_path)
    assert feedback.sample_strength == "insufficient sample size"
    assert feedback.supporting_metrics["views"] == 1000
    assert all("caused" not in item.lower() for item in feedback.recommendations)
    assert (tmp_path / "feedback.json").exists()
    assert (tmp_path / "performance_analysis.json").exists()


def test_graph_analytics_and_feedback_state(monkeypatch, tmp_path):
    history = AnalyticsHistory(project_id="analytics-test", video_id="video-1", snapshots=[snapshot("one")])
    class StubAnalytics:
        def collect(self, publication, project_dir):
            return history
        def analyze(self, history, **kwargs):
            from app.agents.analytics_agent import AnalyticsAgent
            return AnalyticsAgent().analyze(history, topic="Visa")
    monkeypatch.setattr("app.graph.workflow.AnalyticsAgent", StubAnalytics)
    monkeypatch.chdir(tmp_path)
    state = VideoState(project_id="analytics-test", topic="Visa", youtube_publication=publication())
    updated = node_analytics(state)
    assert updated["analytics"] == history
    updated = node_feedback(updated)
    assert updated["feedback"] is not None
    assert updated["status"] == "completed"


def test_missing_publication_fails(tmp_path):
    state = VideoState(project_id="x", topic="x")
    updated = node_analytics(state)
    assert updated["status"] == "failed"
    assert "publication" in updated["errors"][0]
