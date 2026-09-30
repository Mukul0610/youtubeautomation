from pathlib import Path

from PIL import Image, ImageDraw


def render_test_frame(output_path: str | Path) -> Path:
    image = Image.new("RGB", (1280, 720), color=(23, 52, 94))
    draw = ImageDraw.Draw(image)
    draw.rectangle((200, 180, 1080, 540), fill=(56, 117, 169))
    draw.text((320, 300), "FinanceVideoEngine", fill=(255, 255, 255))
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output)
    return output
