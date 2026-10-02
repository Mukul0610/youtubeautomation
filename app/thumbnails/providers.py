from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from pydantic import BaseModel, Field

from app.models.thumbnail import ThumbnailRequest


class ThumbnailProviderResult(BaseModel):
    path: str
    width: int = Field(..., gt=0)
    height: int = Field(..., gt=0)
    format: str = "PNG"


class ThumbnailProvider(ABC):
    name: str = "provider"

    @abstractmethod
    def generate(self, request: ThumbnailRequest) -> ThumbnailProviderResult:
        raise NotImplementedError


class MockThumbnailProvider(ThumbnailProvider):
    """Deterministic Pillow provider for local YouTube thumbnail generation."""

    name = "mock"

    def generate(self, request: ThumbnailRequest) -> ThumbnailProviderResult:
        output = Path(request.output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        seed = sum((index + 1) * ord(char) for index, char in enumerate(request.topic))
        image = Image.new("RGB", (request.width, request.height), (18 + seed % 35, 35 + seed % 45, 65 + seed % 70))
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 0, request.width // 3, request.height), fill=(220, 145, 45))
        self._paste_asset(image, request, request.asset_paths[0] if request.asset_paths else None)
        font = self._font(max(48, request.width // 13))
        lines = self._wrap(request.title_text, font, request.width * 0.58, draw)
        x = request.width * 0.38
        y = request.height * 0.22
        for line in lines[:3]:
            draw.text((x + 3, y + 3), line, font=font, fill=(0, 0, 0))
            draw.text((x, y), line, font=font, fill=(255, 255, 255))
            y += font.size + 8
        if request.subtitle_text:
            small = self._font(max(24, request.width // 32))
            draw.text((x, request.height - small.size * 2), request.subtitle_text, font=small, fill=(255, 220, 120))
        image.save(output, format="PNG", optimize=False)
        return ThumbnailProviderResult(path=str(output), width=request.width, height=request.height)

    @staticmethod
    def _paste_asset(canvas: Image.Image, request: ThumbnailRequest, asset_path: str | None) -> None:
        if not asset_path:
            return
        path = Path(asset_path)
        if not path.exists():
            raise ValueError(f"thumbnail asset is missing: {path}")
        try:
            with Image.open(path) as asset:
                asset.load()
                asset.thumbnail((canvas.width // 3, canvas.height * 3 // 4))
                x = (canvas.width // 3 - asset.width) // 2
                y = (canvas.height - asset.height) // 2
                canvas.paste(asset.convert("RGB"), (x, y))
        except (OSError, ValueError) as exc:
            raise ValueError(f"thumbnail asset is unreadable: {path}") from exc

    @staticmethod
    def _font(size: int):
        for path in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf"):
            if Path(path).exists():
                return ImageFont.truetype(path, size=size)
        return ImageFont.load_default()

    @staticmethod
    def _wrap(text: str, font, max_width: float, draw: ImageDraw.ImageDraw) -> list[str]:
        lines: list[str] = []
        current = ""
        for word in text.split():
            candidate = f"{current} {word}".strip()
            if current and draw.textlength(candidate, font=font) > max_width:
                lines.append(current)
                current = word
            else:
                current = candidate
        if current:
            lines.append(current)
        return lines


def build_thumbnail_provider(name: str = "mock") -> ThumbnailProvider:
    if name.lower() == "mock":
        return MockThumbnailProvider()
    raise ValueError(f"Unsupported thumbnail provider: {name}")
