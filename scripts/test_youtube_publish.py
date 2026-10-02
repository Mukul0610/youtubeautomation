from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.youtube_publisher import YouTubePublisher
from app.config import settings
from app.models.final_video import FinalVideo
from app.models.thumbnail import ThumbnailResult

parser = argparse.ArgumentParser(description="Safely smoke-test YouTube publishing.")
parser.add_argument("project_id")
args = parser.parse_args()
project_dir = Path("projects") / args.project_id
final_video = FinalVideo.model_validate_json((project_dir / "final_video.json").read_text(encoding="utf-8"))
thumbnail = ThumbnailResult.model_validate_json((project_dir / "thumbnail.json").read_text(encoding="utf-8"))
if settings.youtube_default_privacy == "public":
    raise SystemExit("Refusing live smoke test while YOUTUBE_DEFAULT_PRIVACY=public; use private or unlisted.")
result = YouTubePublisher().publish(
    args.project_id,
    final_video.project_id or args.project_id,
    final_video,
    thumbnail,
    project_dir=project_dir,
)
print("Provider:", settings.youtube_provider)
print("Video ID:", result.video_id)
print("URL:", result.video_url)
print("Privacy:", result.privacy_status.value)
print("Thumbnail uploaded:", result.thumbnail_uploaded)
print("Saved:", project_dir / "youtube.json")
