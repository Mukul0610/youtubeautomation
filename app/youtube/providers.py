from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import settings
from app.models.youtube import YouTubeUploadRequest, YouTubeUploadResult


class YouTubeProvider(ABC):
    name: str = "provider"

    @abstractmethod
    def upload_video(self, request: YouTubeUploadRequest) -> YouTubeUploadResult:
        raise NotImplementedError


class MockYouTubeProvider(YouTubeProvider):
    name = "mock"

    def upload_video(self, request: YouTubeUploadRequest) -> YouTubeUploadResult:
        if not Path(request.video_path).exists():
            raise ValueError("mock YouTube upload video file is missing")
        if not Path(request.thumbnail_path).exists():
            raise ValueError("mock YouTube upload thumbnail file is missing")
        video_id = f"mock-{request.project_id}"
        return YouTubeUploadResult(
            project_id=request.project_id,
            video_id=video_id,
            video_url=f"https://example.invalid/mock-youtube/{video_id}",
            channel_id=request.channel_id,
            privacy_status=request.privacy_status,
            upload_status="uploaded",
            thumbnail_uploaded=True,
            published_at=datetime.now(timezone.utc),
            title=request.title,
            description=request.description,
            tags=request.tags,
            category_id=request.category_id,
            is_mock=True,
        )

    def upload_thumbnail(self, video_id: str, thumbnail_path: str) -> None:
        if not Path(thumbnail_path).exists():
            raise ValueError("mock YouTube thumbnail file is missing")


class GoogleYouTubeProvider(YouTubeProvider):
    """Official YouTube Data API v3 provider with installed-app OAuth."""

    name = "google"
    scopes = ["https://www.googleapis.com/auth/youtube.upload"]

    def __init__(self, client_secret_file: str, token_file: str):
        if not client_secret_file:
            raise ValueError("YOUTUBE_CLIENT_SECRET_FILE is required for Google YouTube provider")
        self.client_secret_file = Path(client_secret_file)
        self.token_file = Path(token_file)
        self.youtube = self._build_client()

    def _build_client(self):
        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
            from googleapiclient.discovery import build
        except ImportError as exc:
            raise RuntimeError(
                "Google YouTube provider requires google-api-python-client and google-auth-oauthlib"
            ) from exc
        credentials = None
        if self.token_file.exists():
            credentials = Credentials.from_authorized_user_file(str(self.token_file), self.scopes)
        if credentials and credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
        if not credentials or not credentials.valid:
            if not self.client_secret_file.exists():
                raise FileNotFoundError(f"YouTube client secret file is missing: {self.client_secret_file}")
            flow = InstalledAppFlow.from_client_secrets_file(str(self.client_secret_file), self.scopes)
            credentials = flow.run_local_server(port=0)
        self.token_file.parent.mkdir(parents=True, exist_ok=True)
        self.token_file.write_text(credentials.to_json(), encoding="utf-8")
        return build("youtube", "v3", credentials=credentials)

    def upload_video(self, request: YouTubeUploadRequest) -> YouTubeUploadResult:
        try:
            from googleapiclient.http import MediaFileUpload
            body = {
                "snippet": {
                    "title": request.title,
                    "description": request.description,
                    "tags": request.tags,
                    "categoryId": request.category_id,
                },
                "status": {"privacyStatus": request.privacy_status.value},
            }
            insert = self.youtube.videos().insert(
                part="snippet,status",
                body=body,
                media_body=MediaFileUpload(request.video_path, chunksize=8 * 1024 * 1024, resumable=True),
            )
            response = self._execute_resumable(insert)
            video_id = response.get("id")
            if not video_id:
                raise RuntimeError("YouTube upload returned no video ID")
        except Exception as exc:
            raise RuntimeError(f"YouTube video upload failed: {exc}") from exc

        thumbnail_uploaded = False
        thumbnail_error = None
        try:
            self.youtube.thumbnails().set(
                videoId=video_id,
                media_body=MediaFileUpload(request.thumbnail_path, mimetype="image/png"),
            ).execute()
            thumbnail_uploaded = True
        except Exception as exc:
            thumbnail_error = str(exc)
        return YouTubeUploadResult(
            project_id=request.project_id,
            video_id=video_id,
            video_url=f"https://www.youtube.com/watch?v={video_id}",
            channel_id=request.channel_id,
            privacy_status=request.privacy_status,
            upload_status="uploaded",
            thumbnail_uploaded=thumbnail_uploaded,
            thumbnail_error=thumbnail_error,
            published_at=datetime.now(timezone.utc),
            title=request.title,
            description=request.description,
            tags=request.tags,
            category_id=request.category_id,
            is_mock=False,
        )

    def upload_thumbnail(self, video_id: str, thumbnail_path: str) -> None:
        try:
            from googleapiclient.http import MediaFileUpload
            self.youtube.thumbnails().set(
                videoId=video_id,
                media_body=MediaFileUpload(thumbnail_path, mimetype="image/png"),
            ).execute()
        except Exception as exc:
            raise RuntimeError(f"YouTube thumbnail upload failed: {exc}") from exc

    @staticmethod
    def _execute_resumable(request: Any) -> dict:
        response = None
        while response is None:
            _, response = request.next_chunk()
        return response


def build_youtube_provider(name: str | None = None) -> YouTubeProvider:
    selected = (name or settings.youtube_provider).lower()
    if selected == "mock":
        return MockYouTubeProvider()
    if selected == "google":
        return GoogleYouTubeProvider(settings.youtube_client_secret_file, settings.youtube_token_file)
    raise ValueError(f"Unsupported YouTube provider: {selected}")
