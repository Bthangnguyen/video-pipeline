# VideoDesign Refactor Status

Status: extraction complete, cleanup checkpoint. Branch:
`codex/refactor-videodesign-boundaries`.

This document records the current state of the extraction-only refactor in
`docs/refactor-plan.md`. API routes, persisted project JSON, Redis payloads, DOM IDs, and
visible product behavior remain compatibility constraints.

## Verification At This Checkpoint

```text
python -m compileall -q app                    -> pass
python -m pytest -q                            -> 83 passed
node --check app/static/videodesign/**/*.js    -> pass
node --test tests/js/videodesign-utils.test.mjs -> 2 passed
git diff --check                               -> pass
```

The Python suite includes the VideoDesign route contract, legacy project compatibility,
and local ES-module import resolution. Browser/layout verification is intentionally omitted
from this checkpoint at the user's request. The local `design template/` directory remains
untracked and is not part of the refactor.

## Completed

### Phase 1: Characterization And Test Boundaries

- Split the former 2,003-line VideoDesign test file by project, voiceover, Materials,
  Studio, render, and SFX domains.
- Added fixed route-contract and legacy-project compatibility coverage.
- Kept every VideoDesign test file below 650 lines.

Commit: `fd765bc Split VideoDesign characterization tests by domain`.

### Phase 2: Materials Backend

- Extracted search-plan normalization and shared-pool planning to
  `materials/search_plan.py`.
- Extracted candidate/source handling and proxy creation to Materials-owned modules.
- Extracted keyword generation, source search, review, approval, download, and pruning to
  `materials/service.py`.
- Preserved DeepSeek, yt-dlp, Douyin, Pinterest, and facade monkeypatch points.

Commits:

- `9b87f50 Extract material search planning helpers`
- `c240475 Extract VideoDesign materials service`

### Phase 3: Voiceover And SFX

- Extracted global/scene TTS, combined voiceover, timing offsets, and caption timing to
  `voiceover_service.py`.
- Extracted the SFX catalog, event suggestions, transition mappings, and timeline
  application to `studio/sfx.py`.
- Extracted shared project selectors and preview invalidation to `project_state.py`.

Commits:

- `9943fa9 Extract VideoDesign voiceover service`
- `c851a28 Extract event-driven SFX domain`

### Phase 4: Studio, Render, And Facade

- Extracted smooth-preview/export orchestration and FFmpeg graphs to `studio/render.py`.
- Extracted timeline creation, clips, music, item CRUD, and transitions to
  `studio/service.py`.
- Extracted project creation, scripts, planning, scene updates, split, and merge to
  `project_service.py`.
- Reduced `VideoDesignService` from 3,883 lines to a 584-line compatibility facade.

Commits:

- `5008b54 Extract VideoDesign render pipeline`
- `1660a10 Extract Studio timeline service`
- `3db3d02 Reduce VideoDesignService to a facade`

### Phase 5: Frontend Core, Project, And Materials

- Converted the VideoDesign frontend to native ES modules without adding a build tool.
- Extracted state, API, UI, pure utilities, project workflow, and Materials workflow.
- Added a static import-resolution test and Node tests for pure frontend helpers.

Commits:

- `a89eeb2 Introduce VideoDesign frontend module core`
- `c9b4cca Extract Project and Materials frontend modules`

### Phase 6: Studio Frontend And CSS

- Reduced `videodesign/main.js` to a three-line bootstrap and moved top-level workflow
  orchestration to `workflow.js`.
- Split Studio ownership across `audio.js`, `panels.js`, `playback.js`, `stage.js`, and
  `timeline.js`, coordinated by `studio/index.js`.
- Split the original 2,975-line stylesheet into shared, VideoDesign base, Materials,
  Studio, and responsive stylesheets while preserving cascade order.
- Kept all production Python, JavaScript, and CSS files below 1,000 lines.

This Phase 6 checkpoint is committed together with this status update.

## Current File Sizes

```text
app/videodesign/service.py                         584 lines
app/videodesign/studio/service.py                  598 lines
app/videodesign/materials/search_plan.py           762 lines
app/videodesign/materials/service.py               697 lines
app/static/videodesign/main.js                       3 lines
app/static/videodesign/materials.js                798 lines
app/static/videodesign/studio/playback.js          770 lines
app/static/videodesign/studio/panels.js            719 lines
app/static/style.css                               710 lines
app/static/styles/videodesign-studio.css           990 lines
```

The largest production Python, JavaScript, or CSS file is now 990 lines.

## Remaining Cleanup

- Remove facade compatibility imports only after tests and callers no longer patch them.
- Add focused Node tests when Studio behavior next changes; extraction itself remains
  covered by syntax and import-resolution gates.
- Consider splitting `app/api/videodesign.py` only if route ownership becomes difficult to
  scan. It is not required by the current size target.
- Run product-flow and responsive browser acceptance when visual QA is requested again.

No further structural extraction is required to meet the metrics in the refactor plan.
