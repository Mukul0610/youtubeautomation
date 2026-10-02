from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageDraw, ImageFont

from app.config import settings
from app.models.assets import AssetRegistry
from app.models.rendered import RenderedScene, RenderedScenes
from app.models.storyboard import Storyboard, StoryboardScene
from app.models.tts import TTSResult
from app.tts.providers import read_wav_duration


class SceneRenderer:
    """Render independent storyboard scenes to MP4 with Pillow and FFmpeg."""

    def __init__(self, width: int | None = None, height: int | None = None, fps: int | None = None):
        self.width = width or settings.video_width
        self.height = height or settings.video_height
        self.fps = fps or settings.video_fps
        self._images: dict[str, Image.Image] = {}
        self._font = self._load_font(max(24, self.width // 32))

    def render_project(
        self,
        storyboard: Storyboard,
        tts_result: TTSResult,
        registry: AssetRegistry,
        project_dir: str | Path,
        project_id: str | None = None,
    ) -> RenderedScenes:
        if not storyboard or not storyboard.scenes:
            raise ValueError("scene rendering requires a storyboard with scenes")
        directory = Path(project_dir)
        output_dir = directory / "scenes"
        output_dir.mkdir(parents=True, exist_ok=True)
        audio_by_id = {scene.scene_id: scene for scene in tts_result.scenes}
        rendered: list[RenderedScene] = []
        for scene in storyboard.scenes:
            audio = audio_by_id.get(str(scene.id))
            if audio is None:
                raise ValueError(f"missing TTS audio metadata for scene {scene.id}")
            audio_path = directory / audio.audio_path
            self._validate_audio(audio_path, str(scene.id))
            rendered.append(self.render_scene(scene, audio_path, registry, directory, output_dir))
        result = RenderedScenes(project_id=project_id, scenes=rendered)
        self.persist_metadata(result, directory)
        return result

    def render_scene(
        self,
        scene: StoryboardScene,
        audio_path: Path,
        registry: AssetRegistry,
        project_dir: Path,
        output_dir: Path,
    ) -> RenderedScene:
        self._validate_scene(scene)
        self._validate_audio(audio_path, str(scene.id))
        self._validate_scene_assets(scene, registry, project_dir)
        fingerprint = self._fingerprint(scene, audio_path, registry)
        output_path = output_dir / f"{scene.id}.mp4"
        if output_path.exists() and self._valid_cached_output(output_path, fingerprint):
            return RenderedScene(
                scene_id=str(scene.id), video_path=str(output_path.relative_to(project_dir)),
                duration_seconds=read_wav_duration(audio_path)[0], width=self.width,
                height=self.height, fps=self.fps, audio_path=str(audio_path.relative_to(project_dir)),
                fingerprint=fingerprint, claim_ids=scene.claim_ids,
            )

        duration = read_wav_duration(audio_path)[0]
        frame_count = max(1, round(duration * self.fps))
        ffmpeg = self._ffmpeg_path()
        command = [
            ffmpeg, "-y", "-f", "rawvideo", "-vcodec", "rawvideo",
            "-pix_fmt", "rgb24", "-s", f"{self.width}x{self.height}", "-r", str(self.fps),
            "-i", "-", "-i", str(audio_path), "-t", f"{duration:.6f}",
            "-map", "0:v:0", "-map", "1:a:0", "-c:v", "libx264", "-preset", "ultrafast",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(output_path),
        ]
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            for index in range(frame_count):
                frame = self._frame(scene, registry, project_dir, index / self.fps, duration)
                process.stdin.write(frame.tobytes())
            process.stdin.close()
            stderr = process.stderr.read().decode(errors="replace")
            return_code = process.wait()
        except Exception:
            process.kill()
            process.wait()
            raise
        if return_code != 0:
            raise RuntimeError(f"FFmpeg scene render failed for {scene.id}: {stderr[-1000:]}")
        self._validate_video(output_path, duration)
        return RenderedScene(
            scene_id=str(scene.id), video_path=str(output_path.relative_to(project_dir)),
            duration_seconds=duration, width=self.width, height=self.height, fps=self.fps,
            audio_path=str(audio_path.relative_to(project_dir)), fingerprint=fingerprint,
            claim_ids=scene.claim_ids,
        )

    def _frame(self, scene: StoryboardScene, registry: AssetRegistry, project_dir: Path, elapsed: float, duration: float) -> Image.Image:
        background = next((asset for asset in registry.assets if asset.asset_id == scene.background), None)
        try:
            canvas = self._asset_image(scene.background, registry, project_dir, (self.width, self.height)) if background else None
        except ValueError:
            canvas = None
        if canvas is None:
            seed = sum((index + 1) * ord(char) for index, char in enumerate(str(scene.background)))
            canvas = Image.new("RGB", (self.width, self.height), (20 + seed % 50, 35 + seed % 55, 60 + seed % 70))
        canvas = self._camera(canvas, scene.camera, elapsed / max(duration, 0.001))
        draw = ImageDraw.Draw(canvas)
        for index, asset_id in enumerate(scene.characters):
            image = self._asset_image(asset_id, registry, project_dir, (self.width // 4, self.height // 2))
            if image:
                x = self.width // 12 if index % 2 == 0 else self.width * 3 // 4
                canvas.paste(image, (x, self.height // 3), image if image.mode == "RGBA" else None)
        for index, asset_id in enumerate(scene.props):
            image = self._asset_image(asset_id, registry, project_dir, (self.width // 6, self.height // 4))
            if image:
                x = self.width // 2 + index * (self.width // 8)
                canvas.paste(image, (min(x, self.width - image.width), self.height * 2 // 3), image if image.mode == "RGBA" else None)
        if scene.on_screen_text:
            self._draw_text(draw, scene.on_screen_text)
        canvas = self._fade(canvas, scene.transition, elapsed, duration)
        return canvas.convert("RGB")

    def _asset_image(self, asset_id: str, registry: AssetRegistry, project_dir: Path, size: tuple[int, int]) -> Image.Image | None:
        asset = next((item for item in registry.assets if item.asset_id == asset_id), None)
        if asset is None:
            raise ValueError(f"scene references missing visual asset: {asset_id}")
        path = project_dir / asset.path
        if not path.exists():
            raise ValueError(f"visual asset file is missing: {path}")
        key = f"{path}:{size}"
        if key not in self._images:
            try:
                with Image.open(path) as image:
                    image.load()
                    self._images[key] = image.convert("RGBA").resize(size)
            except (OSError, ValueError) as exc:
                raise ValueError(f"visual asset is unreadable: {path}") from exc
        return self._images[key].copy()

    @staticmethod
    def _validate_scene_assets(scene: StoryboardScene, registry: AssetRegistry, project_dir: Path) -> None:
        asset_ids = [scene.background, *scene.characters, *scene.props]
        known = {asset.asset_id: asset for asset in registry.assets}
        for index, asset_id in enumerate(asset_ids):
            asset = known.get(asset_id)
            if asset is None:
                if index == 0:
                    continue
                raise ValueError(f"scene references missing visual asset: {asset_id}")
            path = project_dir / asset.path
            if not path.exists() or path.stat().st_size == 0:
                if index == 0:
                    continue
                raise ValueError(f"visual asset file is missing: {path}")
            try:
                with Image.open(path) as image:
                    image.verify()
            except (OSError, ValueError) as exc:
                if index == 0:
                    continue
                raise ValueError(f"visual asset is unreadable: {path}") from exc

    def _camera(self, image: Image.Image, camera: str, progress: float) -> Image.Image:
        command = camera.lower()
        pan = "pan left" in command or "pan right" in command
        scale = 1.06 if pan else 1.0
        scale += 0.06 * progress if "zoom in" in command else -0.06 * progress if "zoom out" in command else 0
        if scale != 1.0:
            size = (round(image.width * scale), round(image.height * scale))
            image = image.resize(size)
            max_left = max(0, image.width - self.width)
            if "pan right" in command:
                left = round(max_left * progress)
            elif "pan left" in command:
                left = round(max_left * (1 - progress))
            else:
                left = max_left // 2
            top = max(0, (image.height - self.height) // 2)
            image = image.crop((left, top, left + self.width, top + self.height))
        return image

    @staticmethod
    def _fade(image: Image.Image, transition: str, elapsed: float, duration: float) -> Image.Image:
        if "fade" not in transition.lower():
            return image
        progress = min(1.0, max(0.0, elapsed / max(duration, 0.001)))
        edge = min(1.0, progress / 0.15, (1.0 - progress) / 0.15)
        if edge >= 1.0:
            return image
        return Image.blend(Image.new("RGB", image.size, "black"), image.convert("RGB"), edge)

    def _draw_text(self, draw: ImageDraw.ImageDraw, text: str) -> None:
        margin = self.width // 16
        box = (margin, self.height - self.height // 6, self.width - margin, self.height - margin)
        draw.rounded_rectangle(box, radius=16, fill=(0, 0, 0, 180))
        words = text.split()
        lines: list[str] = []
        current = ""
        for word in words:
            candidate = f"{current} {word}".strip()
            if draw.textlength(candidate, font=self._font) > box[2] - box[0] - 40 and current:
                lines.append(current)
                current = word
            else:
                current = candidate
        if current:
            lines.append(current)
        draw.multiline_text((box[0] + 20, box[1] + 20), "\n".join(lines), font=self._font, fill="white", spacing=8)

    @staticmethod
    def _load_font(size: int):
        for candidate in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf"):
            if Path(candidate).exists():
                return ImageFont.truetype(candidate, size=size)
        return ImageFont.load_default()

    @staticmethod
    def _validate_scene(scene: StoryboardScene) -> None:
        if not str(scene.id).strip() or not scene.narration.strip():
            raise ValueError("scene ID and narration are required")

    @staticmethod
    def _validate_audio(path: Path, scene_id: str) -> None:
        if not path.exists():
            raise ValueError(f"missing audio for scene {scene_id}: {path}")
        try:
            read_wav_duration(path)
        except ValueError as exc:
            raise ValueError(f"invalid audio for scene {scene_id}: {path}") from exc

    def _fingerprint(self, scene: StoryboardScene, audio_path: Path, registry: AssetRegistry) -> str:
        referenced = {scene.background, *scene.characters, *scene.props}
        payload = {
            "scene": scene.model_dump(mode="json"),
            "audio": {"path": str(audio_path), "mtime_ns": audio_path.stat().st_mtime_ns, "size": audio_path.stat().st_size},
            "assets": [asset.model_dump(mode="json") for asset in registry.assets if asset.asset_id in referenced],
            "config": {"width": self.width, "height": self.height, "fps": self.fps},
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

    def _valid_cached_output(self, path: Path, fingerprint: str) -> bool:
        metadata_path = path.with_suffix(".json")
        if not metadata_path.exists() or path.stat().st_size == 0:
            return False
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            if metadata.get("fingerprint") != fingerprint:
                return False
            self._validate_video(path, float(metadata["duration_seconds"]))
            return True
        except (OSError, ValueError, KeyError, json.JSONDecodeError):
            return False

    def _validate_video(self, path: Path, expected_duration: float) -> None:
        if not path.exists() or path.stat().st_size == 0:
            raise ValueError(f"rendered scene is missing or empty: {path}")
        command = [self._ffmpeg_path(), "-hide_banner", "-i", str(path), "-f", "null", "-"]
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode != 0:
            raise ValueError(f"rendered scene is unreadable: {path}: {result.stderr[-500:]}")
        if expected_duration <= 0:
            raise ValueError(f"rendered scene has invalid duration: {path}")
        output = result.stderr
        video_match = re.search(r"Video:.*?(\d{2,5})x(\d{2,5}).*?(\d+(?:\.\d+)?) fps", output, re.IGNORECASE | re.DOTALL)
        audio_present = re.search(r"Stream #\d+:\d+.*Audio:", output, re.IGNORECASE) is not None
        if video_match is None or (int(video_match.group(1)), int(video_match.group(2))) != (self.width, self.height):
            raise ValueError(f"rendered scene has unexpected resolution: {path}")
        if abs(float(video_match.group(3)) - self.fps) > 0.5:
            raise ValueError(f"rendered scene has unexpected FPS: {path}")
        if not audio_present:
            raise ValueError(f"rendered scene has no audio stream: {path}")

    @staticmethod
    def _ffmpeg_path() -> str:
        try:
            import imageio_ffmpeg
            return imageio_ffmpeg.get_ffmpeg_exe()
        except ImportError as exc:
            raise RuntimeError("imageio-ffmpeg is required for MP4 scene rendering") from exc

    @staticmethod
    def persist_metadata(result: RenderedScenes, project_dir: str | Path) -> Path:
        path = Path(project_dir) / "rendered_scenes.json"
        path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
        for scene in result.scenes:
            video_path = Path(project_dir) / scene.video_path
            video_path.with_suffix(".json").write_text(json.dumps({"fingerprint": scene.fingerprint, "duration_seconds": scene.duration_seconds}, indent=2), encoding="utf-8")
        return path
