# VideoDesign Refactor Status

Status: active, stable checkpoint. Branch: `codex/refactor-videodesign-boundaries`.

This document records the exact handoff point for the refactor described in
`docs/refactor-plan.md`. The refactor is extraction-only: API routes, persisted project JSON,
and visible product behavior must remain compatible.

## Verification At This Checkpoint

```text
python -m compileall -q app  -> pass
python -m pytest -q          -> 81 passed
```

The VideoDesign route-contract test and legacy-project payload test are active. The local
`design template/` directory remains untracked and is not part of any refactor commit.

## Completed

### Phase 1: Characterization And Test Boundaries

- Split the former 2,003-line `tests/test_videodesign.py` into project, voiceover,
  Materials search/planning/download, Studio, render, and SFX test files.
- Kept every VideoDesign test file below 650 lines.
- Added a fixed method/path contract for all `/api/videodesign/*` routes.
- Added compatibility coverage for project payloads created before search pools, smooth
  previews, global voiceover, and scene clips.
- Added shared test helpers without changing production behavior.

Commit: `fd765bc Split VideoDesign characterization tests by domain`.

### Phase 2: Materials Backend

- Extracted shared search-pool normalization, hook/base/exact grouping, keyword cleanup,
  grounding, and legacy-plan compatibility to `materials/search_plan.py`.
- Extracted candidate mapping, source URL/cookie resolution, per-scene materialization,
  recovery, and popularity metadata to `materials/candidates.py`.
- Extracted proxy generation to `materials/proxy.py`.
- Extracted keyword generation, search orchestration, preflight, review, approval, download,
  and pruning to `materials/service.py`.
- Kept `videodesign_service` as the API facade and preserved the existing monkeypatch points
  for DeepSeek, yt-dlp, and preview proxies.

Commits:

- `9b87f50 Extract material search planning helpers`
- `c240475 Extract VideoDesign materials service`

### Phase 3: Voiceover And SFX

- Extracted global/scene TTS, clear TTS, combined voiceover, timing offsets, and caption
  timing updates to `voiceover_service.py`.
- Kept global voiceover as the timing source of truth.
- Extracted the SFX catalog, transition mappings, event suggestions, generated fallback
  tones, and timeline application to `studio/sfx.py`.
- Moved shared project selectors, safe file deletion, preview invalidation, and project
  summary helpers to `project_state.py`.

Commits:

- `9943fa9 Extract VideoDesign voiceover service`
- `c851a28 Extract event-driven SFX domain`

### Phase 4A: Render Backend

- Extracted smooth-preview/export orchestration and the FFmpeg video/audio filter graph to
  `studio/render.py`.
- Added `studio/constants.py` for the shared minimum timeline item duration.
- Preserved the facade-level `_render_smooth_preview_file` patch point used by tests.
- Restored the SFX catalog's `@lru_cache` decorator after mechanical extraction.
- Full suite is green after the extraction.

This render checkpoint is committed together with this status document.

## Current File Sizes

```text
app/videodesign/service.py                  1,190 lines
app/videodesign/materials/search_plan.py      762 lines
app/videodesign/materials/service.py          697 lines
app/videodesign/studio/sfx.py                 658 lines
app/videodesign/studio/render.py              466 lines
app/videodesign/materials/candidates.py       326 lines
app/videodesign/voiceover_service.py          249 lines
app/videodesign/project_state.py              112 lines
```

The original `service.py` baseline was 3,883 lines. It is now 1,190 lines before the Studio
timeline extraction.

## Not Completed

### Phase 4B: Studio Timeline Service

The following still lives in `app/videodesign/service.py` and must move to
`studio/service.py`:

- timeline creation and clearing;
- scene clip updates and timeline synchronization;
- background-music upload and file lookup;
- timeline item create/patch/delete;
- per-scene, apply-all, and randomized transitions;
- scene clip, transform, layer, timeline-bound, and transition helper functions.

Compatibility requirement: `create_studio_timeline()` must continue to use the facade's
preview-proxy patch point so existing tests and integrations behave identically.

### Project Service And Thin Facade

Project creation, script generation, planning, scene split/merge, and project updates still
live directly in `service.py`. After Studio extraction they should move to
`project_service.py`, leaving `VideoDesignService` as a facade below 600 lines.

### Frontend JavaScript

`app/static/videodesign.js` is still the original large global-scope file. It has not yet
been converted to native ES modules. The remaining target modules are:

- `videodesign/state.js`, `api.js`, and `utils.js`;
- `videodesign/project.js`;
- `videodesign/materials.js`;
- `videodesign/studio/panels.js`, `stage.js`, `timeline.js`, and `playback.js`;
- a `videodesign.js` entrypoint below 150 lines.

No frontend behavior has been intentionally changed during the backend extraction.

### CSS

`app/static/style.css` has not been split. VideoDesign base, Materials, and Studio rules still
need to move to separate stylesheets, each below 1,000 lines, while preserving stylesheet
order and mobile behavior.

### Final Cleanup And QA

- Remove temporary facade compatibility imports after owning-module tests no longer patch
  them.
- Add Node tests for pure frontend helpers and a static local-import resolver check.
- Update `docs/architecture.md` after module boundaries are final.
- Run desktop/mobile browser acceptance for project creation, Materials, Studio playback,
  timeline interaction, smooth preview, and export.
- Confirm no production Python or JavaScript file exceeds 1,000 lines and no stylesheet
  exceeds 1,000 lines.

## Recommended Next Step

Extract `StudioService` first. Its methods and helper functions are already the largest
remaining cohesive block in `service.py`; moving them should reduce the facade close to the
600-line target without touching frontend behavior. Run the Studio, render, SFX, and full
test suites before committing that extraction.
