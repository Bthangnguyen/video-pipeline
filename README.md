# Douyin Search Module Specs

This repository is scoped to one module only: `douyinsearch`.

The module searches Douyin by keyword using cookies and Playwright, returns normalized video results, and exposes backend stream/proxy endpoints so results can be previewed directly in a web UI.

Anything outside this module, such as project editing, timeline, rendering, captions, or other media sources, is intentionally out of scope until this module is complete.

## Module Goal

Build a clean, reusable Douyin search module that can later be integrated into a larger automation platform.

## Module Responsibilities

- Load and validate Douyin cookies.
- Search Douyin keywords through a real browser session.
- Optionally try the direct Douyin web API as a fast path.
- Normalize search results into a stable response shape.
- Resolve playable video streams.
- Stream video through the backend for browser preview.
- Report typed errors for cookie, captcha, network, and parsing failures.

## Non-Goals

- Project management.
- Timeline editing.
- FFmpeg rendering.
- Multi-source search.
- TikTok or other source adapters.
- Full authentication or multi-user workspace.

## Specs

- [Module Product Spec](docs/product-spec.md)
- [Module Architecture](docs/architecture.md)
- [Douyin Search Design](docs/modules/douyin-search.md)
- [API Contracts](docs/api-contracts.md)
- [Data Model](docs/data-model.md)
- [Implementation Plan](docs/implementation-plan.md)

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
