# Video Design Module Spec

Status: playable V1 slice implemented for project creation, split planning, TTS timing/audio generation, Douyin material search with progress, review, approved-video download, persisted project JSON, timeline JSON creation, and a Studio preview UI. Final FFmpeg rendering is not implemented yet.

Working package name: `videodesign`.

## Product Goal

`videodesign` turns an idea or script into a reviewable video plan, finds Douyin source videos for each script segment, lets the user approve or replace the proposed media, generates an English voiceover, then opens a studio-style timeline for manual visual editing.

The module sits after `douyinsearch`:

```text
idea or script
-> DeepSeek script generation when needed
-> video design preset
-> scene plan
-> English TTS + text timing
-> Douyin material search
-> user approval board
-> download approved videos
-> studio timeline
-> render/export module later
```

## Primary User

A creator/operator who wants AI to assemble a short-form video from script scenes, but still wants control over which source videos are used before entering a timeline editor.

## Core Requirements

- Use `douyinsearch` as the first material source.
- Generate scripts through the DeepSeek API when the user provides an idea, topic, or rough outline instead of a final script.
- Support user-provided scripts without rewriting them unless the user asks for generation or cleanup.
- Generate English TTS for the approved script using a free or free-tier voice provider, prioritizing a clear and pleasant voice.
- Let the user choose how frequently the script is split into scenes before material search.
- Treat each script segment as a separate Douyin search unit.
- Support two ways to assign material to a scene:
  - keyword matching generated from the scene
  - manual user selection from Douyin search results
- Before stock/material search, let the user choose the video design preset:
  - aspect ratio
  - template/layout
  - caption/text animation style
  - transition pack
  - overlay pack
  - default icon/shape pack
- Every generated video has visible animated text/captions by default.
- Text shown on video must match the voiceover timing. Captions should follow the spoken words; headline/text overlays should appear during the matching spoken segment.
- Before studio, show a review board listing which videos the system plans to use for each script segment.
- Download only user-approved scene videos before studio, so the studio works from stable local material assets instead of temporary search results.
- Only move into studio after the user approves the scene-to-video mapping, or explicitly allows placeholders.
- Studio must show a timeline with scene text, media layers, caption layers, text overlays, transitions, and optional icons/shapes that can be dragged on the video canvas and timed on the timeline.

## Non-Goals For V1

- Final FFmpeg rendering.
- Multi-source material beyond Douyin.
- Full team collaboration.
- Advanced AI avatar generation.
- Paid voice marketplace features.
- Voice cloning.
- Automatic publishing.

V1 should output a render-ready timeline JSON that a later render module can consume.

## Main Workflow

### 1. Create Video Design Project And Script

Inputs:

- idea/topic or script text
- target platform, for example TikTok, Shorts, Reels
- aspect ratio, default `9:16`
- target duration
- language
- optional style brief

Example:

```json
{
  "idea": "fun facts about cats ignoring their owners",
  "script": null,
  "target_platform": "tiktok",
  "aspect_ratio": "9:16",
  "target_duration_seconds": 45,
  "language": "en",
  "style_brief": "fast educational short with bold captions"
}
```

If `script` is empty, `videodesign` calls the DeepSeek API to generate the script.

DeepSeek output should be structured, not freeform prose:

```json
{
  "title": "Why Cats Ignore You",
  "hook": "Your cat knows your voice. It just may not care.",
  "script": "Your cat can recognize your voice...",
  "scenes": [
    {
      "voiceover_text": "Your cat can recognize your voice.",
      "on_screen_text": "Cats know your voice",
      "visual_brief": "close-up cat turning toward a human voice",
      "search_keywords": ["cat reacting to owner voice", "funny cat listening"]
    }
  ]
}
```

DeepSeek should not choose final Douyin videos. It only writes the script, scene intent, and initial search keywords.

### 2. Choose Design Preset Before Material Search

The user chooses or accepts an auto-selected preset before Douyin search starts.

The preset constrains media matching. A clip that looks relevant can still be rejected if it does not leave room for captions or text overlays.

Preset fields:

```json
{
  "template_id": "shorts_bold_center",
  "aspect_ratio": "9:16",
  "caption_style_id": "word_reveal_bold",
  "text_animation_id": "rise_pop",
  "transition_pack_id": "fast_swipes",
  "overlay_pack_id": "clean_gradient_shadow",
  "icon_pack_id": "arrows_shapes_basic",
  "safe_zones": {
    "caption": "bottom_30",
    "headline": "top_20"
  }
}
```

Important behavior:

- Captions are enabled by default.
- Text animation is part of the design preset, not a late export effect.
- Transition choice affects ideal clip pacing and cut frequency.
- Safe zones are used while ranking candidate videos.

### 3. Split Or Normalize Script Into Scenes

The module splits the script into scene-sized units, or normalizes DeepSeek's scene output when script generation was used. Each scene gets:

- voiceover text
- TTS text, usually identical to voiceover text
- on-screen headline or short text
- caption chunks
- visual intent
- matching keywords
- expected duration
- template scene assignment

The user can choose scene pacing before scene planning. The planner should parse the script by natural scene beats first, not by a fixed word count:

```json
{
  "split_mode": "auto",
  "target_scene_duration_seconds": 4,
  "min_scene_duration_seconds": 2.5,
  "max_scene_duration_seconds": 7,
  "max_words_per_scene": 18,
  "allow_manual_boundaries": true
}
```

V1 split modes:

```text
auto      Currently behaves like normal; later this can use AI topic-shift detection.
dense     Shorter scenes, usually one sentence per scene.
normal    Balanced pacing, preserving sentence and line-break rhythm.
sparse    Longer scenes, merging short sentences around the target duration.
manual    User line breaks are treated as scene boundaries.
```

Split rules:

- A scene should contain one visual idea, not multiple unrelated ideas.
- A scene should usually fit one Douyin source video.
- If the voiceover is long, split by sentence rhythm or topic shift.
- `max_words_per_scene` is a soft safety limit for overlong sentences, not a fixed target.
- If the template uses fast transitions, prefer shorter scenes.
- If the script has user-provided line breaks, preserve them as strong split hints.
- After splitting, show the scene list and allow the user to merge, split, or rewrite a scene before Douyin search starts.

Example:

```json
{
  "scene_id": "scn_001",
  "order": 1,
  "voiceover_text": "Cats can recognize their owner's voice.",
  "tts_text": "Cats can recognize their owner's voice.",
  "on_screen_text": "Cats know your voice",
  "caption_text": "Cats can recognize their owner's voice",
  "visual_brief": "close-up cat reacting to human voice, indoor home, funny educational tone",
  "matching_keywords": ["cat reacting to owner voice", "funny cat listens", "indoor cat close up"],
  "negative_keywords": ["cartoon", "dog", "wild animal"],
  "duration_seconds": 4.2,
  "template_scene_id": "hook_headline_center"
}
```

### 4. Generate English TTS And Sync Text

After scenes are created, the module generates English TTS per scene.

V1 requirements:

- language defaults to `en`
- default voice should be clear, warm, and easy to listen to
- prefer a free or free-tier TTS provider
- keep provider replaceable later, but avoid adding multiple providers in V1 unless needed
- store generated audio per scene
- estimate or extract word timings for captions
- use TTS duration as the source of truth for scene duration

Recommended V1 voice priority:

```text
1. Free neural English voice adapter if available in the runtime
2. Free local/offline TTS voice if neural voice is unavailable
3. Typed TTS_PROVIDER_UNAVAILABLE error if no free voice can run
```

The exact provider can be decided during implementation, but the module API should expose the selected `voice_id` and `provider`.

Text matching rules:

- `caption_text` must match the spoken `tts_text`, except for punctuation and casing cleanup.
- Word-by-word or phrase captions must be timed from TTS audio where possible.
- If exact word timings are unavailable, use proportional timing based on word count and scene audio duration.
- `on_screen_text` can be a shorter headline, but it must appear during the related voiceover segment.
- Studio must let the user edit text, but edits that change captions should mark TTS sync as stale until regenerated or re-timed.

Example TTS metadata:

```json
{
  "scene_id": "scn_001",
  "voice_id": "english_friendly_default",
  "provider": "free_tts",
  "audio_url": "/api/videodesign/projects/vdp_001/scenes/scn_001/audio",
  "duration_seconds": 4.35,
  "caption_chunks": [
    {"text": "Cats can recognize", "start": 0.0, "end": 1.4},
    {"text": "their owner's voice", "start": 1.4, "end": 2.8}
  ],
  "sync_state": "synced"
}
```

### 5. Search Douyin Materials Per Scene

For each approved scene segment, the module calls `douyinsearch` using generated keywords. This is the data collection stage.

The first version should keep matching simple and inspectable:

1. Take the final scene list from the split step.
2. Generate 1-3 Douyin search keywords per scene.
3. Call `POST /api/douyin/search` separately for each scene.
4. Normalize returned Douyin results into `MediaCandidate`.
5. Keep returned candidates grouped by source and scene for user review.
6. Show the exact keyword used so the user can edit and search again.

One scene must not silently reuse another scene's search results unless the user explicitly copies that media choice.

Search task example:

```json
{
  "search_task_id": "dst_001",
  "scene_id": "scn_001",
  "query_index": 1,
  "keyword": "funny cat listening to owner voice",
  "translate_to_chinese": true,
  "limit": 12,
  "status": "completed",
  "candidate_count": 8
}
```

For Douyin V1, available signals are limited to title, description, author, duration, cover, dimensions, and raw metadata from `douyinsearch`. Candidate quality is decided by user preview, not by an unstable scoring system.

Candidate list requirements per scene:

- show the proposed primary video first
- show 3-5 alternatives when available
- show cover, title, author, duration, source, and search keyword
- allow inline preview through `stream_url`
- allow manual keyword search for that same scene
- keep rejected candidates hidden unless the user asks to restore them

### 6. Review Board Before Studio

Before timeline/studio, show a review board. This is the required approval gate.

Each row represents one scene:

- scene number
- voiceover text
- on-screen text
- selected template scene
- primary proposed Douyin video
- 3-5 alternative candidates
- source and search keyword used
- controls:
  - approve
  - reject
  - search again
  - manually search Douyin
  - pick a different candidate
  - download approved video
  - leave placeholder

The user can enter studio only when:

- all required scenes have an approved and downloaded media selection, or
- the user explicitly confirms placeholders for missing scenes.

Scene approval states:

```text
planned
searching
needs_review
approved
download_pending
downloaded
rejected
placeholder_allowed
```

Download behavior:

- The system does not download every candidate.
- Only the selected candidate for an approved scene is downloaded.
- Download uses `GET /api/douyin/results/{result_id}/download`.
- Downloaded files become `MaterialAsset` records owned by `videodesign`.
- If no-watermark download fails, the scene returns to `needs_review` with `DOWNLOAD_FAILED` and lets the user choose another candidate or retry.
- Studio uses downloaded material assets by default, not expiring Douyin result IDs.

### 7. Studio Handoff

After approval, the module creates a timeline draft.

The timeline draft should include:

- scene rail
- downloaded media asset per approved scene
- voiceover audio per scene
- caption layer for every scene
- headline/text overlay layer when available
- transition items between scenes
- optional icon/shape layers
- timing derived from scene duration

Default layers per scene:

```text
media_base
voiceover_audio
caption_default
text_overlay
transition_out
```

Implemented V1 Studio preview:

- displays the first selected media scene in a 9:16 preview stage
- serves downloaded `MaterialAsset` files through `/api/videodesign/projects/{project_id}/materials/{asset_id}/file`
- overlays caption and headline text from the timeline
- shows media, caption, text, and audio layer tracks
- lets the user click scene buttons or timeline clips to preview a scene
- shows raw timeline JSON for debugging and future render handoff

Optional layers:

```text
icon
shape
sticker
arrow
audio_sfx
b_roll
watermark
```

## Studio Requirements

### Canvas

The canvas previews the current scene with the selected media, captions, text overlays, and icons.

User can:

- drag text/icon/shape layers on the video
- resize layers
- rotate icons/shapes
- change opacity
- change text style
- change caption position

### Timeline

The timeline must show:

- scenes laid out in order
- media clip blocks
- caption/text blocks
- icon/shape blocks
- transition blocks
- current playhead

User can:

- adjust icon start/end time
- adjust text overlay timing
- trim scene media within available duration
- reorder scene blocks later, if enabled
- snap layers to scene boundaries

### Icon And Shape Layer

Icons are normal timeline layers, not static decorations.

Example icon layer:

```json
{
  "layer_id": "lay_arrow_001",
  "type": "icon",
  "icon": "arrow-right",
  "scene_id": "scn_001",
  "start_seconds": 1.2,
  "end_seconds": 3.4,
  "position": {"x": 62, "y": 38},
  "size": {"width": 18, "height": 18},
  "rotation": -12,
  "style": {
    "color": "#ffffff",
    "shadow": true
  },
  "animation": {
    "in": "pop",
    "out": "fade"
  }
}
```

## Data Model

### VideoDesignProject

```json
{
  "project_id": "vdp_001",
  "status": "draft",
  "idea": "fun facts about cats ignoring their owners",
  "script_source": "deepseek",
  "script": "...",
  "aspect_ratio": "9:16",
  "design_preset": {},
  "split_settings": {
    "split_mode": "normal",
    "target_scene_duration_seconds": 4,
    "max_words_per_scene": 18
  },
  "tts_settings": {
    "language": "en",
    "provider": "free_tts",
    "voice_id": "english_friendly_default"
  },
  "scenes": [],
  "created_at": "2026-07-06T00:00:00Z"
}
```

### ScenePlan

```json
{
  "scene_id": "scn_001",
  "order": 1,
  "voiceover_text": "",
  "tts_text": "",
  "on_screen_text": "",
  "caption_text": "",
  "caption_chunks": [],
  "visual_brief": "",
  "matching_keywords": [],
  "template_scene_id": "",
  "duration_seconds": 0,
  "search_tasks": [],
  "tts": {
    "provider": "",
    "voice_id": "",
    "audio_url": "",
    "sync_state": "pending"
  },
  "approval_state": "planned",
  "selected_candidate_id": null,
  "material_asset_id": null
}
```

### DouyinSearchTask

```json
{
  "search_task_id": "dst_001",
  "project_id": "vdp_001",
  "scene_id": "scn_001",
  "keyword": "funny cat listening to owner voice",
  "translate_to_chinese": true,
  "limit": 12,
  "status": "completed",
  "douyin_query_id": "dq_001",
  "candidate_ids": ["cand_001", "cand_002"],
  "error": null
}
```

### MediaCandidate

```json
{
  "candidate_id": "cand_001",
  "source": "douyinsearch",
  "scene_id": "scn_001",
  "douyin_result_id": "dyr_...",
  "douyin_aweme_id": "735...",
  "title": "",
  "cover_url": "/api/douyin/results/dyr_.../cover",
  "stream_url": "/api/douyin/results/dyr_.../stream",
  "download_url": "/api/douyin/results/dyr_.../download",
  "duration": 12.5,
  "match_reason": "Douyin result 1 for scene 1.",
  "status": "proposed"
}
```

### MaterialAsset

Downloaded source video approved for a scene.

```json
{
  "asset_id": "mat_001",
  "project_id": "vdp_001",
  "scene_id": "scn_001",
  "candidate_id": "cand_001",
  "source": "douyinsearch",
  "douyin_result_id": "dyr_...",
  "douyin_aweme_id": "735...",
  "local_path": "./storage/videodesign/vdp_001/materials/scn_001.mp4",
  "media_type": "video/mp4",
  "duration": 12.5,
  "download_state": "downloaded"
}
```

### TimelineDraft

```json
{
  "timeline_id": "tln_001",
  "project_id": "vdp_001",
  "duration_seconds": 45,
  "aspect_ratio": "9:16",
  "scenes": [],
  "layers": [],
  "items": []
}
```

### TimelineItem

```json
{
  "item_id": "itm_001",
  "layer_id": "media_base",
  "scene_id": "scn_001",
  "type": "media",
  "start_seconds": 0,
  "end_seconds": 4.2,
  "source_ref": {
    "source": "material_asset",
    "asset_id": "mat_001"
  },
  "transform": {
    "fit": "cover",
    "x": 50,
    "y": 50,
    "scale": 1,
    "rotation": 0
  }
}
```

## API Draft

Base path:

```text
/api/videodesign
```

### POST `/projects`

Create a draft project from an idea or script and high-level settings.

If a script is provided, the project can skip DeepSeek generation. If only an idea is provided, the next planning step must generate the script through DeepSeek.

### PATCH `/projects/{project_id}/preset`

Set the design preset before material search.

### PATCH `/projects/{project_id}/split-settings`

Set how often the script should be split into scenes.

Request:

```json
{
  "split_mode": "dense",
  "target_scene_duration_seconds": 3,
  "min_scene_duration_seconds": 2,
  "max_scene_duration_seconds": 5,
  "max_words_per_scene": 14,
  "allow_manual_boundaries": true
}
```

### POST `/projects/{project_id}/script/generate`

Generate or regenerate the script through DeepSeek.

Request:

```json
{
  "idea": "fun facts about cats ignoring their owners",
  "target_duration_seconds": 45,
  "tone": "fast educational short",
  "language": "en"
}
```

Response should include the final script plus proposed scene-level voiceover text, on-screen text, visual briefs, and matching keywords.

### POST `/projects/{project_id}/plan`

Split script into scenes and create scene plans using the current split settings.

The response should return the scene list before any Douyin search starts, so the user can merge, split, or edit scenes.

### PATCH `/projects/{project_id}/scenes/{scene_id}`

Edit scene text before material search. Useful when the split is mostly correct but the user wants to adjust voiceover text, on-screen text, visual brief, or keywords.

### POST `/projects/{project_id}/scenes/{scene_id}/split`

Split one scene into two scenes before Douyin search.

### POST `/projects/{project_id}/scenes/merge`

Merge neighboring scenes before Douyin search.

Request:

```json
{
  "scene_ids": ["scn_001", "scn_002"]
}
```

### POST `/projects/{project_id}/tts/generate`

Generate English TTS audio for all scenes or selected scenes.

Request:

```json
{
  "scene_ids": ["scn_001"],
  "provider": "free_tts",
  "voice_id": "english_friendly_default"
}
```

Response should update scene audio URLs, scene durations, caption chunks, and `sync_state`.

### POST `/projects/{project_id}/materials/search`

Run Douyin material search for all scenes or selected scenes. The backend creates one or more `DouyinSearchTask` records per scene and calls `douyinsearch` separately per scene.

Request:

```json
{
  "scene_ids": ["scn_001", "scn_002"],
  "candidates_per_scene": 5,
  "queries_per_scene": 2
}
```

### GET `/projects/{project_id}/review`

Return the review board with proposed videos per scene.

### PATCH `/projects/{project_id}/scenes/{scene_id}/selection`

Approve, reject, replace, or manually assign a Douyin result to a scene.

Example:

```json
{
  "action": "approve",
  "candidate_id": "cand_001"
}
```

Manual assignment:

```json
{
  "action": "manual_select",
  "douyin_result_id": "dyr_..."
}
```

### POST `/projects/{project_id}/materials/download`

Download approved scene videos and create `MaterialAsset` records.

Request:

```json
{
  "scene_ids": ["scn_001", "scn_002"]
}
```

The endpoint should skip scenes that are already downloaded unless `force` is true.

### POST `/projects/{project_id}/studio`

Create a timeline draft from approved and downloaded scenes.

The endpoint should block when a required scene is approved but its selected video has not been downloaded into a `MaterialAsset`.

### GET `/projects/{project_id}/timeline`

Return the current studio timeline.

### PATCH `/projects/{project_id}/timeline/items/{item_id}`

Update layer position, size, timing, style, or animation.

## Configuration Draft

```env
DEEPSEEK_API_KEY=
DEEPSEEK_MODEL=deepseek-chat
VIDEODESIGN_DEFAULT_LANGUAGE=en
VIDEODESIGN_TTS_PROVIDER=free_tts
VIDEODESIGN_TTS_VOICE_ID=english_friendly_default
VIDEODESIGN_STORAGE_DIR=./storage/videodesign
```

Typed errors V1 should expose:

```text
DEEPSEEK_API_KEY_MISSING
SCRIPT_GENERATION_FAILED
TTS_PROVIDER_UNAVAILABLE
TTS_GENERATION_FAILED
TEXT_TTS_SYNC_STALE
DOWNLOAD_FAILED
MEDIA_EXPIRED
```

## Integration With `douyinsearch`

`videodesign` should not scrape Douyin directly.

It should call:

```text
POST /api/douyin/search
GET /api/douyin/results/{result_id}
GET /api/douyin/results/{result_id}/stream
GET /api/douyin/results/{result_id}/download
```

The review board should store module-owned `result_id` references while candidates are being reviewed. After approval, `videodesign` should download selected videos and the studio timeline should store `MaterialAsset` references, not raw Douyin media URLs.

If a Douyin result expires before studio/render, `videodesign` should ask `douyinsearch` to refresh by `douyin_aweme_id` in a later API, or ask the user to re-run material search. V1 can show `MEDIA_EXPIRED`.

## V1 Success Criteria

- User can create a video design project from a script.
- User can generate a script from an idea through DeepSeek API.
- User can choose aspect ratio, template, caption animation, transitions, overlays, and icon pack before material search.
- Script is split into reviewable scenes.
- User can choose split frequency before material search.
- Each scene segment runs its own Douyin search.
- The module generates English TTS with a free or free-tier voice path.
- Scene duration comes from generated TTS audio.
- Captions and visible text are synced to the matching voiceover segment.
- Each scene gets matching keywords and a visual brief.
- The module searches Douyin per scene and proposes candidate videos.
- User sees a review board before studio.
- User can approve, reject, search again, or manually choose a Douyin video for each scene.
- Only approved videos are downloaded.
- Downloaded videos become local material assets.
- Approved and downloaded scenes create a timeline draft.
- Studio shows media, default captions/text, transitions, and optional icon layers.
- User can drag an icon/text layer on the canvas and adjust its timeline timing.
- The module outputs timeline JSON for a later render module.

## Open Questions

- Should missing scenes block studio, or should placeholders be allowed by default?
- Should timeline preview play real remote streams through `douyinsearch`, or only show cover thumbnails until render?
- Which free TTS provider should V1 use by default in the local environment?
