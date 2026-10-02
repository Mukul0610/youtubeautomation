from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Iterable

from pydantic import ValidationError

from app.assets.providers import VisualAssetProvider, build_asset_provider, validate_image
from app.config import settings
from app.models.assets import Asset, AssetRegistry, AssetRequest, AssetType
from app.models.fact_check import ClaimStatus, FactCheckResult
from app.models.storyboard import Storyboard

logger = logging.getLogger(__name__)


class AssetAgent:
    """Plan, generate, validate, and cache visual assets for a storyboard."""

    def __init__(self, provider: VisualAssetProvider | None = None, max_retries: int = 3):
        self.provider = provider or build_asset_provider(settings.asset_provider)
        self.max_retries = max_retries
        self.width = settings.asset_width
        self.height = settings.asset_height
        self.visual_style = settings.visual_style

    def plan(self, storyboard: Storyboard, fact_check: FactCheckResult | None = None) -> list[AssetRequest]:
        if storyboard is None or not storyboard.scenes:
            raise ValueError("Asset planning requires a storyboard with scenes.")
        valid_claims = {claim.claim_id for claim in fact_check.claims} if fact_check else set()
        rejected = {
            claim.claim_id for claim in fact_check.claims
            if claim.status == ClaimStatus.REJECTED
        } if fact_check else set()
        requests: dict[str, AssetRequest] = {}
        for scene in storyboard.scenes:
            claim_ids = list(dict.fromkeys(scene.claim_ids))
            unknown = set(claim_ids) - valid_claims if fact_check else set()
            if unknown:
                raise ValueError(f"scene {scene.id} references unknown claim IDs: {sorted(unknown)}")
            rejected_ids = set(claim_ids) & rejected
            if rejected_ids:
                raise ValueError(f"scene {scene.id} references rejected claim IDs: {sorted(rejected_ids)}")
            self._add_request(requests, scene.background, AssetType.BACKGROUND, "Storyboard background", claim_ids)
            for character in scene.characters:
                self._add_request(requests, character, AssetType.CHARACTER, "Reusable storyboard character", claim_ids)
            for prop in scene.props:
                self._add_request(requests, prop, AssetType.PROP, "Reusable storyboard prop", claim_ids)
        return list(requests.values())

    def generate(
        self,
        storyboard: Storyboard,
        *,
        fact_check: FactCheckResult | None = None,
        project_id: str | None = None,
        project_dir: str | Path | None = None,
    ) -> AssetRegistry:
        if project_dir is None:
            raise ValueError("Asset generation requires a project directory.")
        requests = self.plan(storyboard, fact_check)
        directory = Path(project_dir)
        registry = self.load_registry(directory) or AssetRegistry(project_id=project_id, visual_style=self.visual_style)
        registry.project_id = project_id
        registry.visual_style = self.visual_style
        by_id = {asset.asset_id: asset for asset in registry.assets}
        for request in requests:
            existing = by_id.get(request.asset_id)
            output_path = directory / "assets" / self._asset_folder(request.type) / f"{request.asset_id}.png"
            if existing is not None:
                try:
                    width, height, image_format = validate_image(directory / existing.path)
                    existing.width = width
                    existing.height = height
                    existing.format = image_format.lower()
                    existing.status = "ready"
                    existing.claim_ids = list(dict.fromkeys(existing.claim_ids + request.claim_ids))
                    continue
                except ValueError:
                    pass
            asset = self._generate_one(request, output_path)
            by_id[request.asset_id] = asset
        registry.assets = list(by_id.values())
        self.persist_registry(registry, directory)
        return registry

    def _generate_one(self, request: AssetRequest, output_path: Path) -> Asset:
        last_error: Exception | None = None
        for _ in range(self.max_retries):
            try:
                self.provider.generate_asset(request, output_path, self.width, self.height)
                width, height, image_format = validate_image(output_path)
                if len(output_path.parents) > 2:
                    asset_path = str(output_path.relative_to(output_path.parents[2]))
                else:
                    asset_path = output_path.name
                return Asset(
                    asset_id=request.asset_id,
                    type=request.type,
                    description=request.description,
                    source=self.provider.name,
                    path=asset_path,
                    width=width,
                    height=height,
                    format=image_format.lower(),
                    reusable=request.reusable,
                    claim_ids=request.claim_ids,
                    metadata={"visual_style": self.visual_style},
                )
            except Exception as exc:
                last_error = exc
        raise RuntimeError(
            f"asset provider {self.provider.name} failed for {request.asset_id} "
            f"after {self.max_retries} attempts: {last_error}"
        ) from last_error

    @staticmethod
    def _add_request(
        requests: dict[str, AssetRequest],
        asset_id: str,
        asset_type: AssetType,
        description: str,
        claim_ids: list[str],
    ) -> None:
        asset_id = asset_id.strip()
        if not asset_id:
            raise ValueError(f"{asset_type.value} asset ID cannot be empty")
        if asset_id in requests:
            requests[asset_id].claim_ids = list(dict.fromkeys(requests[asset_id].claim_ids + claim_ids))
            return
        requests[asset_id] = AssetRequest(
            asset_id=asset_id,
            type=asset_type,
            description=description,
            claim_ids=claim_ids,
        )

    @staticmethod
    def _asset_folder(asset_type: AssetType) -> str:
        return {
            AssetType.CHARACTER: "characters",
            AssetType.BACKGROUND: "backgrounds",
            AssetType.PROP: "props",
            AssetType.ICON: "icons",
            AssetType.ILLUSTRATION: "illustrations",
            AssetType.CHART: "charts",
            AssetType.DIAGRAM: "diagrams",
            AssetType.TEXT: "text",
        }[asset_type]

    @staticmethod
    def persist_registry(registry: AssetRegistry, project_dir: str | Path) -> Path:
        path = Path(project_dir) / "assets" / "registry.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(registry.model_dump_json(indent=2), encoding="utf-8")
        return path

    @staticmethod
    def load_registry(project_dir: str | Path) -> AssetRegistry | None:
        path = Path(project_dir) / "assets" / "registry.json"
        if not path.exists():
            return None
        try:
            return AssetRegistry.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, ValidationError):
            return None
