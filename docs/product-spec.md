# Module Product Spec

## Product

`douyinsearch` is a standalone module for searching Douyin videos and previewing results in a browser.

It should be usable by itself during development through a small test UI, and later usable as a backend module inside a larger application.

## Primary User

A developer/operator who wants to search Douyin with a keyword, inspect playable results, and pass selected video metadata to another module later.

## Main Workflow

1. Configure Douyin cookies.
2. Open the module web UI.
3. Enter a keyword.
4. Run search.
5. See normalized video results.
6. Preview a result in the browser.
7. Copy or consume the result payload through API.

## In Scope

- Keyword search.
- Optional keyword translation to Chinese.
- Playwright browser search using cookies.
- Direct Douyin web API search as optional fast path.
- Result normalization.
- Backend stream/proxy for preview.
- Minimal web UI for testing this module.
- Diagnostics for cookie/session/search problems.

## Out Of Scope

- Creating projects.
- Adding videos to timeline.
- Trimming clips.
- Downloading videos for render.
- Captions, overlays, audio, effects.
- Render jobs.
- Integrating TikTok, local upload, or other sources.

## Success Criteria

- A valid cookie file can be loaded and checked.
- A keyword search returns video results.
- Each useful result includes `douyin_aweme_id`, title/description, author, cover, duration when available, and a module-owned `stream_url`.
- A result can be played in the browser through the module backend.
- Search failures return typed errors instead of silent empty results.
