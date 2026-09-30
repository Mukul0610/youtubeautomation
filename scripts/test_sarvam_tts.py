from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings
from app.tts.providers import SarvamTTSProvider, read_wav_duration


text = "Hello, this is a test of the FinanceVideoEngine narration system."
api_key = settings.sarvam_api_key
if not api_key:
    raise SystemExit("Set SARVAM_API_KEY before running this live test.")

output_path = Path("projects/sarvam-live-test/sarvam_test.wav")
provider = SarvamTTSProvider(
    api_key,
    model=settings.tts_model or "bulbul:v3",
    language=settings.tts_language,
    speed=settings.tts_speed,
)
result = provider.synthesize(
    text,
    settings.tts_voice or "shubh",
    output_path,
)
duration, sample_rate = read_wav_duration(output_path)
print("Output:", output_path)
print("Duration seconds:", round(duration, 3))
print("Sample rate:", sample_rate)
print("Provider result:", result.model_dump())
