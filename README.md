# FinanceVideoEngine

Financial storytelling video generation MVP.

## TTS

Phase 6 generates deterministic scene-level mono 16-bit PCM WAV files through
the provider-independent `TTSProvider` interface. The default `mock` provider
needs no API key and writes `projects/<project_id>/audio/scene_*.wav` plus
`tts.json`, which contains actual cumulative timing metadata. Valid cached
audio is reused; missing or corrupt scene files are regenerated individually.

Run the complete test suite with:

```bash
.venv/bin/pytest -q
```

To use Sarvam Bulbul v3, set `TTS_PROVIDER=sarvam`, `SARVAM_API_KEY`,
`TTS_MODEL=bulbul:v3`, `TTS_LANGUAGE=en-IN`, and a compatible `TTS_VOICE` in
`.env`. The optional live smoke test is:

```bash
.venv/bin/python scripts/test_sarvam_tts.py
```

It writes one short test file to `projects/sarvam-live-test/`. Normal tests
use the mock provider and never call Sarvam.
