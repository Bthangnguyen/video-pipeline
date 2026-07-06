# 03 Template And Preset Flow

Status: draft.

Reference screenshots:

- `Screenshot 2026-07-06 215259.png`
- `Screenshot 2026-07-06 215317.png`
- `Screenshot 2026-07-06 215329.png`

## Goal

Let the user decide the video's visual system before scene planning, Douyin search, TTS, and Studio.

The template is not decoration. It controls how scenes are split, which materials fit, where captions go, and what timeline layers are created.

## Route

Preferred future route:

```text
/videodesign/{project_id}/template
```

This screen can also be a tab/section inside:

```text
/videodesign/{project_id}/setup
```

## Layout

```text
left global rail | main preset blocks | sticky right "Your video" summary rail
```

Main blocks:

1. Format & template
2. Scene media
3. Voice & captions
4. Extras & advanced

Right rail:

- shows the current chosen values
- each row can jump to its block
- CTA: `Generate scenes`

## Block 1: Format & Template

### Purpose

Choose aspect ratio and broad template behavior.

### UI

Aspect ratio segmented cards:

- `9:16 Portrait`
- `1:1 Square`
- `16:9 Landscape`

Template category tabs:

- Dynamic Template
- Social Media Story
- Explainer
- Motivation
- Product

Template cards:

- thumbnail preview
- template name
- selected border
- optional tags: `Fast`, `Captions`, `Text-heavy`

### Data

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
    "scene_pacing": "normal",
    "headline_position": "top_safe",
    "caption_position": "bottom_safe"
  }
}
```

### Template Effects

`dynamic_short`:

- default aspect ratio: 9:16
- scene pacing: dense/normal
- captions enabled
- top headline text
- fast transitions

`explainer_clean`:

- scene pacing: normal/sparse
- lower-third captions
- fewer overlays
- longer visual clips allowed

`quote_motivation`:

- scene pacing: sparse
- center text emphasis
- background clips less important than readable text

## Block 2: Scene Media

### Purpose

Choose how scene visuals are sourced.

For this project, default source is Douyin stock.

### UI

Source cards:

- Douyin stock
  - Search video clips with cookies and Playwright.
- Uploads
  - Placeholder for local user uploads.
- Placeholder
  - Use blank/generated placeholders for missing scenes.

Douyin options:

- translate query to Chinese
- candidates per scene
- search mode:
  - one scene at a time
  - batch all scenes

Material constraints:

- prefer vertical clips
- prefer duration >= scene duration
- avoid bottom-heavy captions if template captions are bottom
- avoid duplicate authors/clips across adjacent scenes where possible

### Data

```json
{
  "scene_media": {
    "media_source": "douyin_stock",
    "translate_to_chinese": true,
    "candidate_count": 4,
    "search_mode": "one_scene_at_a_time",
    "safe_zone_priority": "caption_readability"
  }
}
```

## Block 3: Voice & Captions

### Purpose

Set the default voice and caption style before timing is generated.

### UI

Voice row:

- provider select
- voice id select/input
- language
- preview voice placeholder

Provider copy:

- `free_tts`: real audio using edge-tts
- `timing_only`: silent test timing, useful for fast workflow tests

Captions:

- enabled toggle, default on
- caption style gallery

Caption style cards:

- Bold Outline
- Word
- Pop Lime
- Emphasis Pink
- Neon Glow
- Mint Spotlight

Each card should preview the text style in a thumbnail, similar to the reference screenshot.

### Data

```json
{
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
  }
}
```

## Block 4: Extras & Advanced

### Purpose

Choose optional timeline layers before Studio.

### UI

Rows:

- Transition pack
- Overlay pack
- Icon pack
- Brand kit, disabled placeholder

Toggles:

- enable default icon layer
- enable background audio
- enable transition items

### Data

```json
{
  "extras": {
    "transition_pack_id": "fast_swipes",
    "overlay_pack_id": "clean_shadow",
    "icon_pack_id": "arrows_shapes_basic",
    "default_icons_enabled": false,
    "background_audio_enabled": false
  }
}
```

## Right Summary Rail

The rail is always visible on desktop.

Rows:

```text
Format       Portrait 9:16
Template     Dynamic Short
Scene media  Douyin stock
Voiceover    free_tts - en-US-AriaNeural
Captions     Bold Outline
Extras       Transitions on
```

Clicking a row scrolls/focuses the matching block.

CTA:

- `Generate scenes`

CTA behavior:

1. Save `design_preset`.
2. Save split settings derived from template.
3. Navigate to Scene Plan flow.

## Backend Contract

Existing endpoint:

```text
PATCH /api/videodesign/projects/{project_id}/preset
```

Payload:

```json
{
  "format": {},
  "template": {},
  "scene_media": {},
  "voiceover": {},
  "captions": {},
  "extras": {}
}
```

The backend can continue storing this in `project.design_preset` as a dict for V2.

## Acceptance Criteria

- User chooses template before material search.
- Right rail reflects every preset choice.
- Caption style is selected from visual cards.
- Scene media mode clearly states Douyin stock vs upload vs placeholder.
- `free_tts` vs `timing_only` is understandable in the UI.
- Saved preset appears in `project.json`.
- The chosen template can set defaults for scene pacing and timeline layer creation.

