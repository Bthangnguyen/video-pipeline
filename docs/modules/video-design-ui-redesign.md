# Video Design UI Redesign Spec

Status: draft for the next implementation slice.

This spec focuses only on the current web experience for `videodesign`: clearer page flow, visual hierarchy, template/preset selection before generation and material search, and a more useful Studio timeline preview. It does not cover final FFmpeg rendering.

## Reference Screenshots

Source folder:

```text
C:\Users\test123\Documents\automation pipeline\design template
```

Observed product patterns to reuse:

- Landing/create screen: one large prompt entry, direct CTA, minimal navigation.
- Generation setup screen: script editor in the main column, a sticky "Your video" summary rail on the right.
- Preset sections: format, template, scene media, voiceover, captions, avatar, extras are separate expandable blocks.
- Scene media selection: source mode cards, style gallery, model/animation selectors, character/context inputs.
- Caption selection: visual style thumbnails, selected state with strong pink outline.
- Studio screen: left vertical tool rail, scene/script list panel, preview canvas, bottom multi-layer timeline, top action bar.
- Timeline behavior: separate rows for media, voice/caption/text/audio, draggable scene blocks, playhead, zoom and preview controls.

## Product Goal

Make the workflow feel like a guided video creation tool instead of one long technical form.

The user should always understand:

- which stage they are in
- what settings will affect later generation/search
- which scene is being edited
- which video material is selected for each scene
- what the final timeline will contain before render/export exists

## Proposed Page Structure

Detailed per-flow specs:

- [Project Start Flow](video-design-flows/01-project-start-flow.md)
- [Script Creation Flow](video-design-flows/02-script-creation-flow.md)
- [Template And Preset Flow](video-design-flows/03-template-preset-flow.md)
- [Scene Plan And Material Review Flow](video-design-flows/04-scene-plan-material-review-flow.md)
- [Studio Timeline Flow](video-design-flows/05-studio-timeline-flow.md)

### 1. `/videodesign` - Project Start

Purpose: create or load a project.

Layout:

- left global sidebar
  - Home
  - Projects
  - Douyin Search
  - Studio
  - Settings
- center create panel
  - prompt/script textarea
  - target duration slider
  - optional reference attachment placeholder
  - CTA: `Create project`
- recent projects panel or compact list

Behavior:

- If the user enters an idea only, mark script source as `deepseek_pending`.
- If the user enters a full script, mark script source as `user`.
- Store the created project immediately.

### 2. `/videodesign/{project_id}/setup` - Script And Preset

Purpose: decide the video plan before material search starts.

This page replaces the current long vertical wizard for steps 1-4.

Layout:

- left global sidebar
- main column
  - Script block
  - Format & Template block
  - Scene Media block
  - Voice & Captions block
  - Extras block
- right sticky summary rail: `Your video`
  - Format
  - Template
  - Scene media
  - Voiceover
  - Captions
  - Extras
  - CTA: `Generate plan`

Primary actions:

- `Generate with DeepSeek`
- `Use current script`
- `Generate plan`

The right rail is important. It prevents settings from being hidden in long forms and makes the creation state visible before the user starts expensive Douyin searches.

### 3. `/videodesign/{project_id}/plan` - Scene Plan

Purpose: review/edit scene splitting before Douyin search.

Layout:

- top compact project status bar
- left scene list
  - scene number
  - voiceover text
  - duration estimate
  - keywords
  - state badge
- right scene editor
  - voiceover text
  - on-screen text
  - visual brief
  - matching keywords
  - split scene
  - merge with previous/next

Behavior:

- Scene split is natural-language first: sentence and line breaks are primary.
- `max_words_per_scene` remains only a safety limit for overlong sentences.
- User can edit scene text and keywords before Douyin search.
- Any caption/TTS timing becomes stale if voiceover text changes after TTS.

### 4. `/videodesign/{project_id}/materials` - Douyin Material Review

Purpose: run Douyin Search per scene, inspect proposed candidates, approve one per scene.

Layout:

- left scene rail
  - planned
  - searching
  - needs review
  - approved
  - downloaded
- main candidate grid for selected scene
  - primary proposed candidate first
  - alternatives below
  - cover, title, duration, source, search keyword
  - preview/play button
  - approve/reject
- right search panel
  - current keyword
  - manual keyword input
  - query count
  - search again
  - progress log

Behavior:

- Search should default to one scene at a time in the UI.
- A batch search button can exist, but progress must show current scene and keyword.
- User must approve or allow placeholder before Studio.
- Download only approved scene videos.

### 5. `/videodesign/{project_id}/studio` - Studio Timeline

Purpose: preview and adjust timeline composition.

Layout copied from the Studio screenshot:

- top bar
  - project title
  - undo/redo placeholders
  - preview/play controls
  - download/export placeholder disabled until render module exists
- left vertical tool rail
  - Script
  - Media
  - Text
  - Captions
  - Audio
  - Icons
  - Settings
- left panel
  - selected tool content
  - default: Script scene list
- center canvas
  - 9:16 preview
  - selected media video
  - caption overlay
  - text overlay
  - icon/shape overlay later
- bottom timeline
  - scene/media track
  - caption track
  - text overlay track
  - icon/shape track
  - audio track
  - playhead
  - zoom controls

Minimum V2 Studio interactions:

- click a scene block to load it in preview
- drag media block horizontally within timeline
- resize media block edges to adjust start/end
- drag text overlay timing block
- edit text overlay position in the preview canvas
- save updates through `PATCH /api/videodesign/projects/{project_id}/timeline/items/{item_id}`

Dragging should update `TimelineItem.start_seconds`, `TimelineItem.end_seconds`, and, for canvas elements, `TimelineItem.transform`.

## Template And Preset Selection

Template selection must happen before scene planning and Douyin material search because it affects:

- aspect ratio
- caption safe zones
- scene pacing
- target clip duration
- text overlay placement
- candidate suitability

### Preset Blocks

#### Format

Fields:

```json
{
  "aspect_ratio": "9:16",
  "platform": "tiktok",
  "target_duration_seconds": 45
}
```

UI:

- segmented cards: `9:16 Portrait`, `1:1 Square`, `16:9 Landscape`
- target duration slider

#### Template

Fields:

```json
{
  "template_id": "dynamic_short",
  "template_category": "dynamic_template",
  "scene_pacing": "normal",
  "default_layers": ["media_base", "caption_default", "text_overlay", "voiceover_audio"]
}
```

UI:

- horizontal category tabs
  - Dynamic Template
  - Social Media Story
  - Explainer
  - Motivation
  - Product
- template thumbnails
- selected template preview

Template affects:

- default timeline layers
- caption style defaults
- transition defaults
- whether headline text is top, center, or lower third
- recommended scene duration

#### Scene Media

Fields:

```json
{
  "media_source": "douyin_stock",
  "fallback_source": "placeholder",
  "search_strategy": "per_scene_keywords",
  "candidate_count": 4,
  "safe_zone_priority": "caption_readability"
}
```

UI:

- source cards:
  - Douyin stock
  - Uploads
  - Placeholder
- Douyin options:
  - translate query to Chinese
  - candidates per scene
  - search one scene at a time
- template constraints:
  - prefer vertical clips
  - avoid clips with heavy bottom text when captions are bottom
  - prefer clip duration >= scene duration

V1 implementation can keep scoring simple, but the UI should expose why the candidate was proposed.

#### Voiceover

Fields:

```json
{
  "tts_provider": "free_tts",
  "voice_id": "en-US-AriaNeural",
  "language": "en"
}
```

UI:

- provider select
  - `free_tts`: real audio through edge-tts
  - `timing_only`: test mode, silent audio + estimated captions
- voice select/input
- generate timing button

#### Captions

Fields:

```json
{
  "captions_enabled": true,
  "caption_style_id": "bold_outline",
  "caption_position": "bottom_safe",
  "caption_animation_id": "word_reveal"
}
```

UI:

- caption toggle
- style gallery copied from reference:
  - Bold Outline
  - Word
  - Pop Lime
  - Emphasis Pink
  - Neon Glow
  - Mint Spotlight
- selected style with strong border

Captions are enabled by default.

#### Extras

Fields:

```json
{
  "transition_pack_id": "fast_swipes",
  "overlay_pack_id": "clean_shadow",
  "icon_pack_id": "arrows_shapes_basic",
  "brand_kit_enabled": false
}
```

UI:

- transitions picker
- overlay pack picker
- icon pack picker
- brand kit toggle disabled for now if not implemented

## Data Model Changes

Current `design_preset` is a generic `dict`. For the next slice, keep storage flexible but standardize these keys:

```json
{
  "format": {
    "aspect_ratio": "9:16",
    "platform": "tiktok",
    "target_duration_seconds": 45
  },
  "template": {
    "template_id": "dynamic_short",
    "template_category": "dynamic_template",
    "scene_pacing": "normal"
  },
  "scene_media": {
    "media_source": "douyin_stock",
    "candidate_count": 4,
    "translate_to_chinese": true
  },
  "voiceover": {
    "provider": "free_tts",
    "voice_id": "en-US-AriaNeural",
    "language": "en"
  },
  "captions": {
    "enabled": true,
    "style_id": "bold_outline",
    "position": "bottom_safe",
    "animation_id": "word_reveal"
  },
  "extras": {
    "transition_pack_id": "fast_swipes",
    "overlay_pack_id": "clean_shadow",
    "icon_pack_id": "arrows_shapes_basic"
  }
}
```

No new database is required. Continue storing project JSON on disk.

## API Impact

Reuse existing endpoints where possible:

- `PATCH /api/videodesign/projects/{project_id}/preset`
- `PATCH /api/videodesign/projects/{project_id}/split-settings`
- `PATCH /api/videodesign/projects/{project_id}/scenes/{scene_id}`
- `POST /api/videodesign/projects/{project_id}/materials/search`
- `PATCH /api/videodesign/projects/{project_id}/timeline/items/{item_id}`

Likely new endpoints for the next implementation slice:

```text
GET /api/videodesign/projects/{project_id}
POST /api/videodesign/projects/{project_id}/export
POST /api/videodesign/import
POST /api/videodesign/projects/{project_id}/scenes/{scene_id}/materials/search
```

The per-scene material search endpoint is important for the new review page because the UI should not force a full batch search every time a single scene needs better candidates.

## Visual Design Direction

Keep the reference feel:

- mostly light interface for setup pages
- white section panels with 8px border radius
- pink primary CTA
- dark text, muted secondary labels
- strong selected states
- compact icon sidebar
- sticky right summary rail

Studio can stay lighter than the current dark UI:

- white/very light workspace
- dark navy play buttons and active controls
- pastel layer blocks in timeline
- selected scene outline in pink

Avoid marketing hero pages after project creation. Once a project exists, the app should feel like a work tool.

## Implementation Order

1. Add page shell and routing states.
   - `/videodesign`
   - `/videodesign?project_id=...` can continue working temporarily.
   - Add internal views: setup, plan, materials, studio.

2. Build setup page.
   - script editor
   - preset blocks
   - right summary rail
   - save preset into `project.design_preset`

3. Build plan page.
   - scene rail
   - scene editor
   - split/merge controls

4. Build materials page.
   - scene-by-scene search
   - candidate review
   - approve/download flow

5. Build studio page.
   - tool rail
   - preview canvas
   - timeline layer tracks
   - click/select scenes
   - drag/resize first timeline item type

## Acceptance Criteria

- User can create a project without seeing the full technical workflow at once.
- User can choose template, media source, voice, captions, transitions, overlays, and icon pack before material search.
- The right summary rail always reflects the current video configuration.
- Scene planning screen shows editable scenes before Douyin search.
- Material review can search/re-search one scene without rerunning all scenes.
- Studio visually matches the reference structure: tool rail, script/media panel, canvas, timeline.
- Timeline shows separate media, caption, text, icon, and audio tracks.
- At least media and text timeline blocks can be dragged/resized in the browser.
- Project changes continue to persist to `project.json`.
- Existing tests remain green.

## Non-Goals For This Slice

- Final MP4 render.
- Full professional NLE feature set.
- Multi-user project management.
- Paid template marketplace.
- AI avatar generation.
- Brand kit implementation.
