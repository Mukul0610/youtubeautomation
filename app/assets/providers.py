from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from PIL import Image, ImageDraw
from pydantic import BaseModel, Field

from app.models.assets import AssetRequest


class AssetResult(BaseModel):
    path: str
    width: int = Field(..., gt=0)
    height: int = Field(..., gt=0)
    format: str = "PNG"


class VisualAssetProvider(ABC):
    name: str = "provider"

    @abstractmethod
    def generate_asset(self, request: AssetRequest, output_path: Path, width: int, height: int) -> AssetResult:
        raise NotImplementedError


class MockAssetProvider(VisualAssetProvider):
    name = "mock"

    def generate_asset(self, request: AssetRequest, output_path: Path, width: int, height: int) -> AssetResult:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        image = Image.new("RGB", (width, height), self._color(request.asset_id))
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 0, width - 1, height - 1), outline=(255, 255, 255), width=max(1, width // 320))
        label = f"{request.type.value}: {request.asset_id}"
        draw.text((width // 20, height // 20), label, fill=(255, 255, 255))
        image.save(output_path, format="PNG")
        return AssetResult(path=str(output_path), width=width, height=height)

    @staticmethod
    def _color(asset_id: str) -> tuple[int, int, int]:
        value = sum((index + 1) * ord(char) for index, char in enumerate(asset_id))
        return (40 + value % 100, 60 + value % 80, 90 + value % 100)


def validate_image(path: Path) -> tuple[int, int, str]:
    if not path.exists() or path.stat().st_size == 0:
        raise ValueError(f"asset file is missing or empty: {path}")
    try:
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            width, height = image.size
            image_format = image.format or ""
    except (OSError, ValueError) as exc:
        raise ValueError(f"asset file is corrupt or unreadable: {path}") from exc
    if width <= 0 or height <= 0:
        raise ValueError(f"asset dimensions are invalid: {path}")
    return width, height, image_format


def build_asset_provider(name: str = "mock") -> VisualAssetProvider:
    if name.lower() == "mock":
        return MockAssetProvider()
    raise ValueError(f"Unsupported asset provider: {name}")
