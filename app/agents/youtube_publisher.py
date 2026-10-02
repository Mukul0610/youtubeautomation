from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PIL import Image
from pydantic import ValidationError

from app.config import settings
from app.models.final_video import FinalVideo
from app.models.script import Script
from app.models.thumbnail import ThumbnailResult
from app.models.youtube import YouTubePrivacy, YouTubeUploadRequest, YouTubeUploadResult
from app.youtube.providers import YouTubeProvider, build_youtube_provider


class YouTubePublisher:
    """Build safe metadata and publish one completed project idempotently."""

    def __init__(self, provider: YouTubeProvider | None = None):
        self.provider = provider or build_youtube_provider()

    def publish(
        self,
        project_id: str,
        topic: str,
        final_video: FinalVideo,
        thumbnail: ThumbnailResult,
        *,
        script: Script | None = None,
        project_dir: str | Path,
        force_republish: bool = False,
    ) -> YouTubeUploadResult:
        directory = Path(project_dir)
        record_path = directory / "youtube.json"
        if record_path.exists() and not force_republish:
            try:
                cached = YouTubeUploadResult.model_validate_json(record_path.read_text(encoding="utf-8"))
                if cached.upload_status == "uploaded":
                    return cached
            except (OSError, ValueError, ValidationError):
                pass
        video_path = directory / final_video.video_path
        thumbnail_path = directory / thumbnail.thumbnail_path
        self._validate_inputs(video_path, thumbnail_path, final_video, thumbnail)
        request = YouTubeUploadRequest(
            project_id=project_id,
            video_path=str(video_path),
            thumbnail_path=str(thumbnail_path),
            title=self._title(topic),
            description=self._description(topic, script),
            tags=self._tags(topic),
            category_id=settings.youtube_category_id,
            privacy_status=YouTubePrivacy(settings.youtube_default_privacy),
            channel_id=settings.youtube_channel_id or None,
        )
        result = self.provider.upload_video(request)
        if not result.thumbnail_uploaded and result.video_id:
            result = self._retry_thumbnail(result, request.thumbnail_path)
        record_path.parent.mkdir(parents=True, exist_ok=True)
        record_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
        return result

    @staticmethod
    def _validate_inputs(video: Path, thumbnail: Path, final_video: FinalVideo, thumbnail_result: ThumbnailResult) -> None:
        if not video.exists() or video.stat().st_size == 0:
            raise ValueError(f"YouTube publishing video is missing: {video}")
        if not thumbnail.exists() or thumbnail.stat().st_size == 0:
            raise ValueError(f"YouTube publishing thumbnail is missing: {thumbnail}")
        try:
            with Image.open(thumbnail) as image:
                image.verify()
            with Image.open(thumbnail) as image:
                if image.format != "PNG" or image.size != (thumbnail_result.width, thumbnail_result.height):
                    raise ValueError("thumbnail metadata does not match the image")
        except (OSError, ValueError) as exc:
            raise ValueError(f"invalid YouTube thumbnail: {thumbnail}") from exc
        if final_video.scene_count <= 0:
            raise ValueError("final video has no scenes")

    def _retry_thumbnail(self, result: YouTubeUploadResult, thumbnail_path: str) -> YouTubeUploadResult:
        upload_thumbnail = getattr(self.provider, "upload_thumbnail", None)
        if upload_thumbnail is None:
            return result
        try:
            upload_thumbnail(result.video_id, thumbnail_path)
            result.thumbnail_uploaded = True
            result.thumbnail_error = None
        except Exception as exc:
            result.thumbnail_error = str(exc)
        return result

    @staticmethod
    def _title(topic: str) -> str:
        title = " ".join(topic.split()).strip()
        return title[:100]

    @staticmethod
    def _description(topic: str, script: Script | None) -> str:
        lines = [f"This finance explainer explores {topic.strip()}."]
        if script and script.sections:
            headings = [section.heading for section in script.sections[:6]]
            lines.append("\nTopics covered: " + ", ".join(headings) + ".")
        lines.append("\nThis video is for educational purposes only and is not financial advice.")
        return "\n".join(lines)

    @staticmethod
    def _tags(topic: str) -> list[str]:
        words = [word.strip(".,:;!?\"'").lower() for word in topic.split()]
        tags = [word for word in words if len(word) > 2]
        tags.extend(["finance", "business", "economics"])
        return list(dict.fromkeys(tags))[:12]
