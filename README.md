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

## Scene Rendering

Phase 8 renders each storyboard scene independently to an MP4 in
`projects/<project_id>/scenes/`. Pillow creates deterministic frames and
`imageio-ffmpeg` supplies the local FFmpeg encoder for MP4/audio muxing. The
renderer consumes the existing storyboard, TTS metadata, and asset registry;
it does not combine scenes into a final video. Per-scene fingerprints allow
unchanged scenes to be reused.

## Final Composition

Phase 9 concatenates validated scene MP4 files in Storyboard order into
`projects/<project_id>/final_video.mp4`. Metadata is stored in
`final_video.json`; a composition fingerprint reuses a valid unchanged output,
and temporary output is replaced only after validation.

## Thumbnail Generation

Phase 10 creates a deterministic 1280x720 PNG from existing storyboard assets
and topic text. It writes `thumbnail.png` and `thumbnail.json`, uses the
provider-independent `ThumbnailProvider` abstraction, and reuses unchanged
outputs through a fingerprint cache. Run its tests with:

```bash
.venv/bin/pytest tests/unit/test_thumbnail_agent.py -q
```

## Visual assets

Phase 7 plans deterministic character, background, and prop assets from the
Storyboard and writes reusable PNG files plus `assets/registry.json`. The mock
provider requires no API key; duplicate IDs are reused and missing or corrupt
images are regenerated individually. Set `ASSET_PROVIDER`, `VISUAL_STYLE`,
`ASSET_WIDTH`, and `ASSET_HEIGHT` to configure the asset system.

## YouTube Publishing

Phase 11 publishes the completed MP4 and thumbnail through a provider-independent
`YouTubeProvider`. The default is `YOUTUBE_PROVIDER=mock`, which writes a
deterministic `youtube.json` without network access. The Google provider uses
official YouTube Data API v3 resumable uploads and installed-app OAuth; keep
client secrets in `credentials/` and tokens in `tokens/`, both ignored by Git.
Set `YOUTUBE_DEFAULT_PRIVACY=private` or `unlisted` for safe testing. Existing
successful `youtube.json` records are reused unless `force_republish=True` is
explicitly requested.

Optional smoke command:

```bash
.venv/bin/python scripts/test_youtube_publish.py <project_id>
```
