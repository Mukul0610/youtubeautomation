from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image
from pydantic import ValidationError

from app.config import settings
from app.models.assets import AssetRegistry, AssetType
from app.models.final_video import FinalVideo
from app.models.storyboard import Storyboard
from app.models.thumbnail import ThumbnailRequest, ThumbnailResult
from app.thumbnails.providers import ThumbnailProvider, build_thumbnail_provider


class ThumbnailAgent:
    """Select existing visual assets and create a deterministic thumbnail."""

    def __init__(self, provider: ThumbnailProvider | None = None):
        self.provider = provider or build_thumbnail_provider(settings.thumbnail_provider)
        self.width = 1280
        self.height = 720
        self.template_id = "finance_explainer"

    def generate(
        self,
        project_id: str,
        topic: str,
        registry: AssetRegistry,
        storyboard: Storyboard,
        *,
        final_video: FinalVideo | None = None,
        project_dir: str | Path,
    ) -> ThumbnailResult:
        if not project_id.strip():
            raise ValueError("thumbnail generation requires a project ID")
        if not topic.strip():
            raise ValueError("thumbnail generation requires a topic")
        if not registry or not registry.assets:
            raise ValueError("thumbnail generation requires a visual asset registry")
        if final_video is None:
            raise ValueError("thumbnail generation requires a composed final video")
        directory = Path(project_dir).resolve()
        asset_ids, asset_paths = self._select_assets(registry, storyboard, directory)
        title_text = self._headline(topic)
        fingerprint = self._fingerprint(project_id, topic, title_text, asset_ids, registry)
        output = directory / "thumbnail.png"
        metadata = directory / "thumbnail.json"
        cached = self._load_cache(metadata, output, fingerprint)
        if cached is not None:
            return cached
        request = ThumbnailRequest(
            project_id=project_id,
            topic=topic,
            title_text=title_text,
            asset_ids=asset_ids,
            asset_paths=asset_paths,
            template_id=self.template_id,
            output_path=str(output),
            width=self.width,
            height=self.height,
        )
        temp = directory / "thumbnail.tmp.png"
        temp.unlink(missing_ok=True)
        request.output_path = str(temp)
        result = self.provider.generate(request)
        try:
            self._validate_image(temp)
            temp.replace(output)
            final = ThumbnailResult(
                project_id=project_id,
                thumbnail_path="thumbnail.png",
                width=self.width,
                height=self.height,
                format="PNG",
                title_text=title_text,
                subtitle_text=None,
                asset_ids=asset_ids,
                template_id=self.template_id,
                fingerprint=fingerprint,
                created_at=datetime.now(timezone.utc),
            )
            metadata.write_text(final.model_dump_json(indent=2), encoding="utf-8")
            return final
        except Exception:
            temp.unlink(missing_ok=True)
            raise

    @staticmethod
    def _headline(topic: str) -> str:
        words = [word.strip(".,:;!?\"") for word in topic.split() if word.strip(".,:;!?\"")]
        if len(words) <= 6:
            return " ".join(words).upper()
        if "how" in topic.lower() and "makes" in topic.lower():
            subject = topic.lower().split("how", 1)[1].split("makes", 1)[0].strip()
            return f"HOW {subject.upper()}\nMAKES MONEY"
        return " ".join(words[:5]).upper()

    @staticmethod
    def _select_assets(registry: AssetRegistry, storyboard: Storyboard, directory: Path) -> tuple[list[str], list[str]]:
        referenced: list[str] = []
        for scene in storyboard.scenes:
            referenced.extend([scene.background, *scene.characters, *scene.props])
        by_id = {asset.asset_id: asset for asset in registry.assets}
        ordered = list(dict.fromkeys(referenced))
        missing = [asset_id for asset_id in ordered if asset_id not in by_id]
        if missing:
            raise ValueError(f"thumbnail asset is missing from registry: {missing[0]}")
        preferred = [asset_id for asset_id in ordered if by_id[asset_id].type in {AssetType.CHARACTER, AssetType.ILLUSTRATION, AssetType.PROP}]
        selected = preferred[:2] or ordered[:1]
        if not selected:
            raise ValueError("thumbnail requires at least one selected visual asset")
        paths = []
        for asset_id in selected:
            path = directory / by_id[asset_id].path
            if not path.exists():
                raise ValueError(f"thumbnail asset is missing: {path}")
            paths.append(str(path))
        return selected, paths

    def _fingerprint(self, project_id: str, topic: str, title_text: str, asset_ids: list[str], registry: AssetRegistry) -> str:
        payload = {
            "project_id": project_id,
            "topic": topic,
            "title_text": title_text,
            "asset_ids": asset_ids,
            "assets": [asset.model_dump(mode="json") for asset in registry.assets if asset.asset_id in asset_ids],
            "template_id": self.template_id,
            "size": [self.width, self.height],
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

    @staticmethod
    def _validate_image(path: Path) -> None:
        if not path.exists() or path.stat().st_size == 0:
            raise ValueError("thumbnail output is missing or empty")
        try:
            with Image.open(path) as image:
                image.verify()
            with Image.open(path) as image:
                if image.format != "PNG" or image.size != (1280, 720):
                    raise ValueError("thumbnail must be a 1280x720 PNG")
        except (OSError, ValueError) as exc:
            raise ValueError(f"invalid thumbnail output: {path}") from exc

    def _load_cache(self, metadata: Path, output: Path, fingerprint: str) -> ThumbnailResult | None:
        if not metadata.exists() or not output.exists():
            return None
        try:
            result = ThumbnailResult.model_validate_json(metadata.read_text(encoding="utf-8"))
            self._validate_image(output)
            return result if result.fingerprint == fingerprint else None
        except (OSError, ValueError, ValidationError):
            return None
