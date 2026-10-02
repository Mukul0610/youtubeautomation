from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.config import settings
from app.models.analytics import AnalyticsRequest, AnalyticsSnapshot, AnalyticsStatus


class AnalyticsProvider(ABC):
    name: str = "provider"

    @abstractmethod
    def get_video_analytics(self, request: AnalyticsRequest) -> AnalyticsSnapshot:
        raise NotImplementedError


class MockAnalyticsProvider(AnalyticsProvider):
    name = "mock"

    def __init__(self, snapshot: AnalyticsSnapshot | None = None):
        self.snapshot = snapshot

    def get_video_analytics(self, request: AnalyticsRequest) -> AnalyticsSnapshot:
        if self.snapshot is not None:
            return self.snapshot.model_copy(deep=True)
        collected = datetime.now(timezone.utc).replace(microsecond=0)
        return AnalyticsSnapshot(
            collected_at=collected,
            fingerprint=f"mock:{request.video_id}:{collected.isoformat()}",
            views=1000,
            watch_time_minutes=2800.0,
            average_view_duration_seconds=168.0,
            average_view_percentage=62.0,
            likes=80,
            comments=20,
            shares=12,
            subscribers_gained=25,
            subscribers_lost=1,
            impressions=12000,
            impressions_click_through_rate=8.3,
            published_at=collected - timedelta(days=7),
            video_age_days=7,
            is_mock=True,
        )


class YouTubeAnalyticsProvider(AnalyticsProvider):
    name = "google"
    scopes = ["https://www.googleapis.com/auth/yt-analytics.readonly"]

    def __init__(self, client_secret_file: str, token_file: str):
        self.client_secret_file = Path(client_secret_file)
        self.token_file = Path(token_file)
        self.analytics = self._build_client()

    def _build_client(self):
        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
            from googleapiclient.discovery import build
        except ImportError as exc:
            raise RuntimeError("Google analytics requires Google API and OAuth libraries") from exc
        credentials = None
        if self.token_file.exists():
            credentials = Credentials.from_authorized_user_file(str(self.token_file), self.scopes)
        if credentials and credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
        if not credentials or not credentials.valid:
            if not self.client_secret_file.exists():
                raise FileNotFoundError(f"YouTube client secret file is missing: {self.client_secret_file}")
            credentials = InstalledAppFlow.from_client_secrets_file(str(self.client_secret_file), self.scopes).run_local_server(port=0)
        self.token_file.parent.mkdir(parents=True, exist_ok=True)
        self.token_file.write_text(credentials.to_json(), encoding="utf-8")
        return build("youtubeAnalytics", "v2", credentials=credentials)

    def get_video_analytics(self, request: AnalyticsRequest) -> AnalyticsSnapshot:
        end = datetime.now(timezone.utc).date()
        start = end - timedelta(days=request.lookback_days)
        try:
            response = self.analytics.reports().query(
                ids="channel==MINE",
                startDate=start.isoformat(),
                endDate=end.isoformat(),
                metrics="views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage,likes,comments,shares,subscribersGained,subscribersLost,impressions,impressionsCtr",
                filters=f"video=={request.video_id}",
            ).execute()
        except Exception as exc:
            raise RuntimeError(f"YouTube Analytics request failed: {exc}") from exc
        rows = response.get("rows", [])
        if not rows:
            return AnalyticsSnapshot(
                collected_at=datetime.now(timezone.utc),
                fingerprint=f"empty:{request.video_id}:{end.isoformat()}",
                status=AnalyticsStatus.PENDING,
            )
        row = rows[0]
        values = dict(zip(response.get("columnHeaders", []), row)) if response.get("columnHeaders") else {}
        return AnalyticsSnapshot(
            collected_at=datetime.now(timezone.utc),
            fingerprint=f"google:{request.video_id}:{end.isoformat()}:{row}",
            views=values.get("views"),
            watch_time_minutes=values.get("estimatedMinutesWatched"),
            average_view_duration_seconds=values.get("averageViewDuration"),
            average_view_percentage=values.get("averageViewPercentage"),
            likes=values.get("likes"), comments=values.get("comments"), shares=values.get("shares"),
            subscribers_gained=values.get("subscribersGained"), subscribers_lost=values.get("subscribersLost"),
            impressions=values.get("impressions"), impressions_click_through_rate=values.get("impressionsCtr"),
        )


def build_analytics_provider(name: str | None = None) -> AnalyticsProvider:
    selected = (name or settings.analytics_provider).lower()
    if selected == "mock":
        return MockAnalyticsProvider()
    if selected == "google":
        return YouTubeAnalyticsProvider(settings.youtube_client_secret_file, settings.youtube_token_file)
    raise ValueError(f"Unsupported analytics provider: {selected}")
