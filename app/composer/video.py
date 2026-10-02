from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path

from app.config import settings
from app.models.final_video import FinalVideo
from app.models.rendered import RenderedScene, RenderedScenes
from app.models.storyboard import Storyboard


class VideoComposer:
    """Concatenate validated rendered scenes into one final MP4."""

    def __init__(self, width: int | None = None, height: int | None = None, fps: int | None = None):
        self.width = width or settings.video_width
        self.height = height or settings.video_height
        self.fps = fps or settings.video_fps

    def compose(
        self,
        storyboard: Storyboard,
        rendered_scenes: RenderedScenes,
        project_dir: str | Path,
        project_id: str | None = None,
    ) -> FinalVideo:
        if storyboard is None or not storyboard.scenes:
            raise ValueError("video composition requires a storyboard with scenes")
        directory = Path(project_dir).resolve()
        ordered = self._ordered_scenes(storyboard, rendered_scenes, directory)
        fingerprint = self._fingerprint(ordered, storyboard)
        output = directory / "final_video.mp4"
        metadata_path = directory / "final_video.json"
        cached = self._load_cache(metadata_path, output, fingerprint, len(ordered))
        if cached is not None:
            return cached

        directory.mkdir(parents=True, exist_ok=True)
        list_path = directory / "final_video.concat.txt"
        temp_output = directory / "final_video.tmp.mp4"
        try:
            list_path.write_text(
                "\n".join(f"file '{self._ffmpeg_quote(directory / scene.video_path)}'" for scene in ordered) + "\n",
                encoding="utf-8",
            )
            temp_output.unlink(missing_ok=True)
            command = [
                self._ffmpeg_path(), "-y", "-f", "concat", "-safe", "0",
                "-i", str(list_path), "-c", "copy", str(temp_output),
            ]
            result = subprocess.run(command, capture_output=True, text=True)
            if result.returncode != 0:
                raise RuntimeError(f"FFmpeg composition failed: {result.stderr[-1500:]}")
            self._validate_video(temp_output, sum(scene.duration_seconds for scene in ordered), len(ordered))
            temp_output.replace(output)
        except Exception:
            temp_output.unlink(missing_ok=True)
            raise
        finally:
            list_path.unlink(missing_ok=True)

        duration = self._probe_video(output, len(ordered))["duration"]
        final = FinalVideo(
            project_id=project_id,
            video_path="final_video.mp4",
            duration_seconds=duration,
            width=self.width,
            height=self.height,
            fps=self.fps,
            scene_count=len(ordered),
            file_size_bytes=output.stat().st_size,
            composition_fingerprint=fingerprint,
            scene_ids=[scene.scene_id for scene in ordered],
        )
        metadata_path.write_text(final.model_dump_json(indent=2), encoding="utf-8")
        return final

    def _ordered_scenes(self, storyboard: Storyboard, rendered: RenderedScenes, directory: Path) -> list[RenderedScene]:
        by_id = {scene.scene_id: scene for scene in rendered.scenes}
        ordered: list[RenderedScene] = []
        for storyboard_scene in storyboard.scenes:
            scene_id = str(storyboard_scene.id)
            scene = by_id.get(scene_id)
            if scene is None:
                raise ValueError(f"Cannot compose project: {scene_id}.mp4 is missing from rendered metadata.")
            path = directory / scene.video_path
            if not path.exists() or path.stat().st_size == 0:
                raise ValueError(f"Cannot compose project: {scene_id}.mp4 is missing.")
            self._validate_video(path, scene.duration_seconds, 1)
            ordered.append(scene)
        return ordered

    def _fingerprint(self, scenes: list[RenderedScene], storyboard: Storyboard) -> str:
        payload = {
            "scenes": [{"id": scene.scene_id, "fingerprint": scene.fingerprint} for scene in scenes],
            "transitions": [scene.transition for scene in storyboard.scenes],
            "config": {"width": self.width, "height": self.height, "fps": self.fps},
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

    def _load_cache(self, metadata_path: Path, output: Path, fingerprint: str, scene_count: int) -> FinalVideo | None:
        if not metadata_path.exists() or not output.exists() or output.stat().st_size == 0:
            return None
        try:
            result = FinalVideo.model_validate_json(metadata_path.read_text(encoding="utf-8"))
            if result.composition_fingerprint != fingerprint or result.scene_count != scene_count:
                return None
            self._validate_video(output, result.duration_seconds, scene_count)
            return result
        except (OSError, ValueError, KeyError):
            return None

    def _validate_video(self, path: Path, expected_duration: float, expected_scene_count: int) -> None:
        probe = self._probe_video(path, expected_scene_count)
        if abs(probe["duration"] - expected_duration) > max(0.25, expected_duration * 0.1):
            raise ValueError(
                f"final video duration mismatch: expected {expected_duration:.2f}s, "
                f"actual {probe['duration']:.2f}s"
            )
        if (probe["width"], probe["height"]) != (self.width, self.height):
            raise ValueError(f"video resolution mismatch: expected {self.width}x{self.height}")
        if abs(probe["fps"] - self.fps) > 0.5:
            raise ValueError(f"video FPS mismatch: expected {self.fps}, actual {probe['fps']}")
        if not probe["audio"]:
            raise ValueError(f"video has no audio stream: {path}")

    def _probe_video(self, path: Path, expected_scene_count: int) -> dict[str, float | int | bool]:
        command = [self._ffmpeg_path(), "-hide_banner", "-i", str(path), "-f", "null", "-"]
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode != 0:
            raise ValueError(f"video is unreadable: {path}: {result.stderr[-1000:]}")
        text = result.stderr
        duration_match = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)", text, re.IGNORECASE)
        video_match = re.search(
            r"Video:.*?(\d{2,5})x(\d{2,5}).*?(\d+(?:\.\d+)?) fps",
            text,
            re.IGNORECASE | re.DOTALL,
        )
        if duration_match is None or video_match is None:
            raise ValueError(f"video stream metadata unavailable: {path}")
        audio = re.search(r"Stream #\d+:\d+.*Audio:", text, re.IGNORECASE) is not None
        return {
            "width": int(video_match.group(1)),
            "height": int(video_match.group(2)),
            "fps": float(video_match.group(3)),
            "duration": int(duration_match.group(1)) * 3600 + int(duration_match.group(2)) * 60 + float(duration_match.group(3)),
            "audio": audio,
        }

    @staticmethod
    def _ffmpeg_quote(path: Path) -> str:
        return str(path).replace("'", "'\\''")

    @staticmethod
    def _ffmpeg_path() -> str:
        try:
            import imageio_ffmpeg
            return imageio_ffmpeg.get_ffmpeg_exe()
        except ImportError as exc:
            raise RuntimeError("imageio-ffmpeg is required for video composition") from exc
