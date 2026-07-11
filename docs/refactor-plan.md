# Codebase Refactor Plan

Status: proposed. Baseline commit: `67df7f0 Add shared material search pools`.

## Objective

Reduce the current god files into domain-owned modules without changing product behavior, API contracts, persisted project JSON, or the no-build frontend deployment model.

The refactor must make the next feature easier to add. Merely moving arbitrary line ranges into smaller files is not sufficient.

## Baseline

Measured after the shared-search-pool implementation:

| File | Lines | Functions | Main concern |
| --- | ---: | ---: | --- |
| `app/static/videodesign.js` | 4,393 | 292 | Project flow, Materials, Studio panels, playback, timeline interaction, API, and utilities share global scope |
| `app/videodesign/service.py` | 3,883 | 171 | Project, TTS, Materials, download, Studio, render, music, transition, and SFX behavior share one service |
| `app/static/style.css` | 2,975 | n/a | Shared search pages, VideoDesign workflow, Materials, and Studio styles share one cascade |
| `tests/test_videodesign.py` | 2,004 | 85 | All VideoDesign domains share fixtures and one test file |
| `app/douyinsearch/browser_client.py` | 615 | 35 | Large, but still one cohesive Playwright browser/session responsibility |
| `app/api/videodesign.py` | 464 | 52 | Repetitive but cohesive FastAPI adapter |

Current verification baseline:

```text
python -m pytest -q          -> 79 passed
node --check videodesign.js -> pass
Desktop/mobile Materials QA -> pass
```

## Refactor Rules

1. Do not combine feature changes with extraction commits.
2. Keep `/api/videodesign/*` routes and response shapes unchanged.
3. Keep `videodesign_service` as the public backend facade during migration.
4. Keep old project JSON and Redis payloads loadable without a migration command.
5. Keep direct object dependencies available on the facade while existing tests patch them, including `script_client`, `tts_client`, and `ytdlp`.
6. Extract pure functions before stateful orchestration.
7. Do not add a dependency-injection framework, repository abstraction, frontend framework, or build tool.
8. Stop after each phase and run the complete verification gate.

## Target Backend Shape

```text
app/videodesign/
  service.py                    # Thin compatibility facade
  schemas.py                    # Keep together while below 600 lines
  project_service.py            # Project, script, scene, progress
  voiceover_service.py          # TTS and combined voiceover
  project_state.py              # Shared selectors and preview-state helpers
  materials/
    __init__.py
    service.py                  # Search, review, approval, download, prune
    search_plan.py              # Shared-pool planning and normalization
    candidates.py               # Candidate mapping and source resolution
  studio/
    __init__.py
    service.py                  # Timeline CRUD, music, transitions
    render.py                   # FFmpeg preview/export graph
    sfx.py                      # Catalog, suggestions, event mapping
```

`VideoDesignService` remains the object imported by the API:

```python
class VideoDesignService:
    def __init__(self):
        self.store = VideoDesignStore()
        self.script_client = DeepSeekScriptClient()
        self.tts_client = TTSClient()
        self.ytdlp = YtDlpDownloader()
        self.projects = ProjectService(self.store, self.script_client)
        self.voiceover = VoiceoverService(self.store, self.tts_client)
        self.materials = MaterialsService(self.store, self.script_client, self.ytdlp)
        self.studio = StudioService(self.store)
```

Facade methods delegate to these services until the API routers are intentionally split later.

## Target Frontend Shape

Use native browser ES modules. No bundler is required.

```text
app/static/
  videodesign.js                # Tiny module entrypoint
  videodesign/
    main.js                     # Bootstrap and top-level render orchestration
    state.js                    # Shared mutable application state
    api.js                      # API, run state, progress polling
    utils.js                    # Pure formatting and DOM helpers
    project.js                  # Start, project library, script, template, TTS
    materials.js               # Search pools, candidates, preview, approval
    studio/
      panels.js                 # Text, captions, overlay, transitions, audio UI
      stage.js                  # Canvas rendering and drag interaction
      timeline.js               # Timeline layout, zoom, seek, resize
      playback.js               # Media/audio/music synchronization
  styles/
    videodesign-base.css
    videodesign-materials.css
    videodesign-studio.css
```

Dependency direction:

```text
main -> feature modules -> state/api/utils
studio panels -> studio timeline/stage/playback
state/api/utils never import feature modules
```

This prevents circular imports and keeps feature modules independently readable.

## Phase 1: Characterization And Test Boundaries

Goal: make later file moves reviewable before production behavior changes.

Changes:

- move shared project/test helpers into `tests/conftest.py`;
- split `tests/test_videodesign.py` into project, voiceover, materials, studio, render, and SFX test files;
- add a persisted-project compatibility test using a payload created before the refactor;
- add a route-contract test that records the existing VideoDesign method/path set;
- add static checks that every frontend module import resolves;
- introduce `tests/js/` with Node's built-in test runner for extracted pure functions;
- do not change production imports in this phase.

Exit criteria:

- all 79 existing tests still pass;
- no test file exceeds 650 lines;
- fixtures do not mutate global service state across tests;
- route and persisted-project compatibility tests are in place.

Suggested commit:

```text
Split VideoDesign characterization tests by domain
```

## Phase 2: Extract The Materials Domain

Goal: move the newest and most frequently changing domain out of `service.py` first.

Move to `materials/search_plan.py`:

- shared pool normalization;
- hook/base/exact grouping;
- keyword normalization and grounding;
- group merge and scene synchronization;
- legacy V2 plan compatibility.

Move to `materials/candidates.py`:

- candidate lookup and mapping;
- candidate popularity metadata;
- source URL/cookie resolution;
- shared-result materialization per scene.

Move to `materials/service.py`:

- keyword/search-plan generation;
- group-based Douyin/Pinterest execution;
- preflight, progress, review, selection;
- download and prune workflows.

Compatibility:

- keep facade methods with the same names;
- temporarily re-export private helpers that tests still import;
- preserve `script_client` and `ytdlp` as shared facade dependencies;
- do not change Material API schemas in this phase.

Exit criteria:

- shared group still produces one source search and per-scene candidates;
- partial results, approval, download, and old projects behave identically;
- `service.py` drops by at least 900 lines;
- Materials modules contain no Studio/render imports.

Suggested commits:

```text
Extract material search planning helpers
Extract VideoDesign materials service
```

## Phase 3: Extract Voiceover And SFX

Goal: remove two independent audio responsibilities from the facade.

Move to `voiceover_service.py`:

- global and scene TTS generation;
- clearing TTS;
- combined voiceover creation;
- scene audio offsets and caption timing updates.

Move to `studio/sfx.py`:

- SFX catalog constants and loading;
- transition-to-SFX mapping;
- event-driven suggestion generation;
- caption-word and icon events;
- applying SFX suggestions to the timeline.

Keep general audio probing/concatenation in the existing `audio.py`.

Exit criteria:

- global TTS remains the source of truth for scene timing;
- SFX output and timeline item shapes do not change;
- no generated/static SFX catalog behavior changes;
- `service.py` contains no SFX constant catalog.

Suggested commits:

```text
Extract VideoDesign voiceover service
Extract event-driven SFX domain
```

## Phase 4: Extract Studio And Rendering

Goal: isolate editor state changes from expensive FFmpeg rendering.

Move to `studio/service.py`:

- timeline creation and clearing;
- timeline item CRUD;
- clip updates;
- music upload and trim state;
- transition selection, apply-all, and randomization.

Move to `studio/render.py`:

- smooth preview and export rendering;
- FFmpeg media, transition, caption, and audio filters;
- video/audio stream probing;
- render output naming and paths.

Move to `project_state.py`:

- project/scene/asset selectors;
- preview stale/reset helpers;
- project summary and stage calculation;
- safe project-owned file deletion.

Important boundary:

```text
StudioService mutates timeline state.
RenderService reads a timeline snapshot and produces a file.
```

Exit criteria:

- realtime Studio and smooth preview use the same persisted timeline contract;
- render output remains byte-compatible in codec/container expectations;
- `service.py` becomes a facade under 600 lines;
- no circular import between Studio, render, Materials, and SFX.

Suggested commits:

```text
Extract Studio timeline service
Extract VideoDesign render pipeline
Reduce VideoDesignService to a facade
```

## Phase 5: Split Frontend Core And Materials

Goal: establish ES-module boundaries before touching the large Studio section.

Changes:

- create `state.js`, `api.js`, and `utils.js` first;
- move project/script/template/TTS functions into `project.js`;
- move all Materials search-pool and candidate functions into `materials.js`;
- make each feature export `bindEvents()` and `render()` entrypoints;
- change `videodesign.js` into a small module entrypoint;
- keep existing DOM IDs, API requests, and visible behavior unchanged;
- add Node tests for pure search-plan and formatting helpers.

Exit criteria:

- project creation through Materials approval still works;
- no feature module imports `main.js`;
- no JS module exceeds 850 lines;
- browser console is clean at desktop and mobile widths.

Suggested commits:

```text
Introduce VideoDesign frontend module core
Extract Materials frontend module
```

## Phase 6: Split Studio Frontend And CSS

Goal: isolate editor rendering, interaction, and playback, then align CSS ownership.

Studio JavaScript split:

- `panels.js`: inspectors and option controls;
- `stage.js`: visual canvas and draggable elements;
- `timeline.js`: ruler, tracks, clips, zoom, drag, resize, playhead;
- `playback.js`: media buffering, transitions, TTS, BGM, and SFX sync.

CSS split:

- leave common Douyin/Pinterest page styling in `style.css`;
- move VideoDesign shell/layout into `videodesign-base.css`;
- move candidate/search-pool rules into `videodesign-materials.css`;
- move Studio/canvas/timeline rules into `videodesign-studio.css`;
- load stylesheets in explicit order from `videodesign.html`;
- do not use CSS `@import`.

Exit criteria:

- realtime and smooth playback remain continuous;
- timeline click/seek, zoom/fit, drag, and resize remain functional;
- caption/icon canvas dragging remains functional;
- no stylesheet exceeds 1,000 lines;
- no horizontal overflow at 390px, 1120px, and 1440px widths.

Suggested commits:

```text
Extract Studio frontend modules
Split VideoDesign styles by feature
```

## Final Cleanup

After all phases are stable:

- remove temporary compatibility re-exports;
- update tests to import helpers from their owning modules;
- update `docs/architecture.md`, which currently describes only the original DouyinSearch scope;
- evaluate splitting `app/api/videodesign.py` only if route ownership is still hard to scan;
- keep `schemas.py` together unless it grows beyond roughly 600 lines;
- keep `douyinsearch/browser_client.py` together unless session, search, and extraction begin changing independently.

## Verification Gate Per Commit

Run after every extraction commit:

```text
python -m pytest -q
node --check <every changed .js file>
node --test tests/js/*.test.mjs   # once Phase 1 adds JS tests
git diff --check
```

Manual browser acceptance after frontend or render changes:

1. Load a persisted project created before the refactor.
2. Generate or edit shared search pools.
3. Search one group and Search all.
4. Preview and approve candidates from both sources.
5. Download materials and recreate the timeline.
6. Verify TTS, BGM, SFX, captions, icons, transitions, seek, drag, and resize.
7. Render smooth preview and export MP4.
8. Check 390x844, 1440x900, and the 1120px layout breakpoint.

## Completion Metrics

- no production Python or JavaScript file exceeds 1,000 lines;
- `app/videodesign/service.py` is a facade below 600 lines;
- `app/static/videodesign.js` is an entrypoint below 150 lines;
- no test file exceeds 650 lines;
- no stylesheet exceeds 1,000 lines;
- all current API routes and persisted models remain compatible;
- all automated and manual acceptance checks pass;
- refactor commits contain no intentional product behavior changes.

## Recommended Starting Point

Start with Phase 1, then extract Materials in Phase 2. Materials has the newest tests and the clearest domain boundary, so it provides the safest proof that the facade approach works before moving Studio and render code.
