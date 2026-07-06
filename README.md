# Video Pipeline Specs

This repository currently implements `douyinsearch` and the playable V1 slice of `videodesign`.

The module searches Douyin by keyword using cookies and Playwright, returns normalized video results, and exposes backend stream/proxy endpoints so results can be previewed directly in a web UI.

`videodesign` now has a linear web workflow for project creation, DeepSeek script generation, natural scene planning, English TTS timing/audio generation, Douyin video matching with progress updates, pre-studio approval, approved-video download, persisted project JSON, and a studio timeline preview that plays downloaded local material assets.

## Current Goal

Build the video pipeline as small modules that can be developed and tested independently before they are connected into a full automation platform.

## Current State

- `douyinsearch` is the source video module.
- `/videodesign` is the second module UI.
- VideoDesign projects are stored under `storage/videodesign/{project_id}/project.json`.
- Scene planning parses scripts by natural sentence/line breaks first. `max_words_per_scene` is only a soft safety limit for overlong sentences.
- `timing_only` TTS is a fast test mode that creates silent audio plus estimated caption timing.
- `free_tts` uses `edge-tts` for a real English voice path.
- Studio preview shows downloaded media, captions/text overlays, layer tracks, and timeline JSON.

## Next Direction

- Import/export full project JSON from the UI so a generated project can be restored without manual recovery.
- Improve scene review editing: rewrite scene text, matching keywords, and visual brief before Douyin search.
- Add manual per-scene Douyin re-search and candidate replacement inside the review board.
- Add draggable text/icon layers on the Studio canvas and timeline timing controls.
- Add a render module that consumes `TimelineDraft` and exports an MP4 with FFmpeg.

## Module Responsibilities

- Load and validate Douyin cookies.
- Search Douyin keywords through a real browser session.
- Optionally try the direct Douyin web API as a fast path.
- Normalize search results into a stable response shape.
- Resolve playable video streams.
- Stream video through the backend for browser preview.
- Download selected search results as no-watermark MP4 when Douyin exposes a resolvable media URL.
- Report typed errors for cookie, captcha, network, and parsing failures.

## Non-Goals For Current V1

- FFmpeg rendering.
- Multi-source search.
- TikTok or other source adapters.
- Full authentication or multi-user workspace.

## Specs

### Implemented Module

- [Module Product Spec](docs/product-spec.md)
- [Module Architecture](docs/architecture.md)
- [Douyin Search Design](docs/modules/douyin-search.md)
- [API Contracts](docs/api-contracts.md)
- [Data Model](docs/data-model.md)
- [Implementation Plan](docs/implementation-plan.md)

### Video Design Module

- [Video Design Module Spec](docs/modules/video-design.md)
- [Video Design UI Redesign Spec](docs/modules/video-design-ui-redesign.md)
- [Video Design Flow Specs](docs/modules/video-design-flows/README.md)

## Run

```bash
pip install -r requirements.txt
python -m playwright install chromium
copy .env.example .env
python -m uvicorn app.main:app --reload --port 2323
```

Open `http://localhost:2323`.

`DOUYIN_USE_DIRECT_API` defaults to `false`. Direct API search is kept for manual research, but `auto` uses Playwright unless this flag is explicitly enabled.

## Test

```bash
pytest -q
```
