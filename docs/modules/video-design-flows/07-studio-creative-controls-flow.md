# 07 Studio Creative Controls Flow

Status: proposed next implementation after trim selection.

## Goal

Define the Studio controls for creative scene editing:

- caption/text display styles, including word-by-word sync with voiceover
- draggable text directly on the preview video
- per-scene overlays
- transitions between scenes, including apply-to-all and random mix
- icons/markers that can be added to a scene, dragged, resized, and timed

This flow should make Studio feel like a practical short-form video editor, not a form editor.

## Product Decision

The Studio editing model is scene-first:

```text
select scene -> choose creative tool -> edit on preview canvas -> persist timeline item
```

The preview canvas is the source of truth for position and size. Numeric controls are secondary.

## Non-Goals

- No advanced After Effects-style keyframing in this slice.
- No large marketplace of templates or icon packs.
- No final FFmpeg export requirement in the first UI slice.
- No AI-based automatic styling decisions beyond applying selected presets.

## Tool Rail

Studio tool rail should include:

```text
Script
Media
Text
Captions
Overlay
Transitions
Icons
Audio
Settings
```

Minimum implementation order:

```text
Text/Captions -> Overlay -> Transitions -> Icons
```

## Text And Captions

Studio needs two separate text concepts:

### Captions

Captions are generated from the voiceover and should match TTS timing.

Use cases:

- subtitle every scene by default
- display word-by-word matching the voice
- highlight the currently spoken word
- preserve template style across scenes

### Text Overlay

Text overlay is editable scene text independent from generated captions.

Use cases:

- short hook text
- emphasis phrase
- CTA text
- manually timed title inside a scene

## Caption Timing Model

Preferred timing source:

```text
TTS word timings -> caption chunks -> proportional fallback
```

Data shape:

```json
{
  "tts": {
    "duration_seconds": 3.42,
    "word_timings": [
      {
        "word": "discipline",
        "start_seconds": 1.2,
        "end_seconds": 1.72,
        "index": 4
      }
    ],
    "timing_quality": "word"
  }
}
```

Fallback when word timing is unavailable:

```json
{
  "timing_quality": "estimated"
}
```

Estimated timing is acceptable for preview, but should be labeled internally so the render/export module can regenerate timing later if a better TTS provider is used.

## Caption Display Modes

Required V1 modes:

```text
Full line
Word reveal
Active word highlight
Typewriter
Two-line karaoke
```

Behavior:

- `Full line`: show the current caption chunk as one line.
- `Word reveal`: words appear one by one as voiceover advances.
- `Active word highlight`: show the whole line, highlight current word.
- `Typewriter`: reveal characters or words progressively.
- `Two-line karaoke`: show surrounding words, highlight current word.

Mode should be stored on the caption timeline item:

```json
{
  "type": "caption",
  "style": {
    "caption_mode": "active_word_highlight",
    "font_family": "Montserrat",
    "font_weight": 800,
    "italic": false,
    "font_size": 54,
    "text_color": "#ffffff",
    "active_word_color": "#38f0b2",
    "stroke_color": "#111111",
    "stroke_width": 4,
    "shadow": true,
    "background": "none",
    "case": "sentence"
  }
}
```

## Text Style Options

Text and caption panels should expose:

- display mode
- font family
- font size
- bold
- italic
- color
- active word color
- outline/stroke color
- outline/stroke width
- shadow on/off
- background pill/none
- uppercase/sentence case
- line height
- alignment
- timing start/end

Recommended font set:

```text
Inter
Montserrat
Poppins
Anton
Bebas Neue
Arial
Georgia
```

Style option buttons should preview the style directly. For example, the button itself renders sample text using that style instead of only naming the style.

## Text Canvas Interaction

Text can be edited on the preview canvas.

Rules:

- click text overlay selects the timeline item
- drag moves position
- resize handle changes scale/font size
- rotate handle can be deferred
- text stays inside safe preview bounds
- drag updates optimistically
- persist on drag end

Transform:

```json
{
  "x": 50,
  "y": 78,
  "scale": 1,
  "rotation": 0
}
```

Coordinates:

- `x` and `y` are percent of preview canvas
- `x=50`, `y=50` is center
- clamp center point to `0..100`

Patch endpoint:

```text
PATCH /api/videodesign/projects/{project_id}/timeline/items/{item_id}
```

Request:

```json
{
  "transform": {
    "x": 52,
    "y": 74,
    "scale": 1.08,
    "rotation": 0
  },
  "style": {
    "font_family": "Montserrat",
    "font_weight": 800,
    "text_color": "#ffffff"
  }
}
```

## Overlay Per Scene

Overlay is a per-scene visual layer that sits above media and below text/icons.

Required V1 overlay options:

```text
None
Soft vignette
Focus frame
Dim background
Top/bottom caption shade
Subtle grain
```

Overlay should be scene-specific. Selecting Scene 3 and changing overlay only affects Scene 3 unless user explicitly applies to all scenes.

Timeline item:

```json
{
  "item_id": "itm_overlay_001",
  "layer_id": "overlay_default",
  "scene_id": "scn_001",
  "type": "overlay",
  "start_seconds": 0,
  "end_seconds": 3.42,
  "source_ref": {
    "overlay_id": "top_bottom_caption_shade"
  },
  "style": {
    "opacity": 0.35,
    "color": "#000000"
  }
}
```

UI behavior:

- Overlay panel shows option swatches.
- Selecting an overlay updates preview immediately.
- User can adjust opacity.
- `Apply to all scenes` duplicates the overlay choice across each scene.

## Transitions

Transitions are applied between two adjacent scenes.

User mental model:

```text
select Scene 1 -> choose transition -> transition is inserted between Scene 1 and Scene 2
```

For the last scene, transition out should be disabled or treated as outro-only later.

Required transition options:

```text
None
Fade
Dissolve
Slide left
Slide right
Slide up
Zoom in
Zoom out
Whip pan
Flash cut
```

V1 should keep duration simple:

```text
0.15s
0.25s
0.35s
0.50s
```

Timeline item:

```json
{
  "item_id": "itm_transition_001",
  "layer_id": "transition_out",
  "scene_id": "scn_001",
  "type": "transition",
  "start_seconds": 3.17,
  "end_seconds": 3.42,
  "source_ref": {
    "from_scene_id": "scn_001",
    "to_scene_id": "scn_002",
    "transition_id": "fade"
  },
  "style": {
    "duration_seconds": 0.25,
    "easing": "ease_out"
  }
}
```

### Transition Actions

The Transitions panel should expose:

```text
Apply to selected cut
Apply to all cuts
Random mix
Clear all transitions
```

Random mix rules:

- only uses safe transition IDs selected by product
- never applies transition after last scene
- stores the generated choice per cut
- random result should persist; it should not reshuffle on reload

Project-level random seed:

```json
{
  "transition_random_seed": "trn_20260709_001"
}
```

## Icons And Markers

Icons are scene-local visual annotations.

Required V1 icon set:

```text
Arrow
Circle
Rectangle
Underline
Check
X mark
Starburst
Pointer
Question mark
Exclamation
```

Use a normal icon library in frontend when possible, such as Lucide icons. Shapes like circle/rectangle/underline can be CSS/SVG primitives.

Timeline item:

```json
{
  "item_id": "itm_icon_001",
  "layer_id": "icon",
  "scene_id": "scn_001",
  "type": "icon",
  "start_seconds": 0.8,
  "end_seconds": 2.4,
  "source_ref": {
    "icon_id": "arrow_right"
  },
  "transform": {
    "x": 62,
    "y": 38,
    "scale": 1,
    "rotation": -12
  },
  "style": {
    "color": "#ffffff",
    "stroke_width": 4,
    "opacity": 1,
    "shadow": true
  }
}
```

## Icon Canvas Interaction

Rules:

- choose scene
- choose icon
- icon is added to current scene timeline
- icon appears on preview canvas
- drag moves icon
- resize handle changes scale
- optional rotation handle later
- timeline block controls icon start/end
- delete key or delete button removes selected icon

Default timing:

```text
start = selected scene local time, or scene start + 0.2s
end = min(scene end, start + 1.8s)
```

If the user is playing the scene and adds an icon, start at current playhead local time.

## Studio Preview Layer Order

Preview canvas layer stack:

```text
media
media effects
scene overlay
caption
text overlay
icons
selection handles
safe-area guides
```

Only the selected overlay/icon/text should show handles.

## Timeline Tracks

Required tracks:

```text
media_base
overlay_default
caption_default
text_overlay
icon
voiceover_audio
background_audio
transition_out
```

Timeline behavior:

- text, captions, overlay, and icons cannot leave their scene bounds
- transition item belongs to the previous scene
- resizing scene media should clamp child items inside the new scene duration

## API Additions

Existing patch item endpoint remains the main update path:

```text
PATCH /api/videodesign/projects/{project_id}/timeline/items/{item_id}
```

Needed endpoints:

```text
POST /api/videodesign/projects/{project_id}/timeline/items
DELETE /api/videodesign/projects/{project_id}/timeline/items/{item_id}
POST /api/videodesign/projects/{project_id}/scenes/{scene_id}/transition
POST /api/videodesign/projects/{project_id}/transitions/apply-all
POST /api/videodesign/projects/{project_id}/transitions/randomize
```

Create timeline item request:

```json
{
  "scene_id": "scn_001",
  "type": "icon",
  "layer_id": "icon",
  "start_seconds": 0.8,
  "end_seconds": 2.4,
  "source_ref": {
    "icon_id": "arrow_right"
  },
  "transform": {
    "x": 62,
    "y": 38,
    "scale": 1,
    "rotation": -12
  },
  "style": {
    "color": "#ffffff"
  }
}
```

Transition request:

```json
{
  "transition_id": "fade",
  "duration_seconds": 0.25,
  "scope": "selected_cut"
}
```

Backend validation:

- scene exists
- timeline exists
- item start/end stays inside scene bounds
- icon/text/caption/overlay items cannot target another project's scene
- transition cannot be applied to last scene unless future outro mode exists
- style values are allowlisted or clamped
- random transitions only use approved transition IDs

## Render Mapping Later

Browser preview should come first. Final render should map Studio decisions to FFmpeg later.

Mapping:

- captions: ASS subtitle or transparent overlay render
- text overlay: ASS/drawtext or pre-rendered transparent frames
- icons: SVG/PNG overlay with position/scale/rotation
- overlays: FFmpeg filter or transparent overlay layer
- transitions: FFmpeg `xfade`

Word-by-word caption animation is easiest to preserve with ASS subtitles or pre-rendered overlay frames. Simple SRT is not enough.

## UI States

No selected scene:

```text
Select a scene to edit creative controls.
```

No TTS timing:

```text
Caption timing pending.
```

Selected text/icon:

- show handles on canvas
- open matching tool panel
- highlight matching timeline item

Transition on last scene:

```text
No next scene for transition.
```

Random mix applied:

```text
Transitions randomized and saved.
```

## Acceptance Criteria

- User can choose caption display mode for selected scene.
- Caption preview can reveal/highlight words in sync with scene audio timing.
- User can change caption/text font, color, bold, italic, outline, shadow, and size.
- Text overlay can be dragged directly on the preview video and persists after reload.
- User can select a per-scene overlay and see it immediately in preview.
- Overlay can be applied to all scenes explicitly.
- User can select Scene 1 and apply a transition between Scene 1 and Scene 2.
- User can apply one transition to all cuts.
- User can randomize transitions across all cuts and the result persists.
- User can add an icon to the selected scene.
- Icon can be dragged and resized directly on the preview video.
- Icon timing can be adjusted on the timeline.
- Existing trim/media preview remains unaffected.

## Implementation Slices

### Slice 1: Text And Caption Style

- add Text/Captions controls
- add style preview buttons
- persist style via timeline item patch
- improve canvas drag/resize for text

### Slice 2: Word-Synced Caption Preview

- add word timing data shape
- implement proportional timing fallback
- preview word reveal and active-word highlight

### Slice 3: Scene Overlay

- add overlay timeline item controls
- implement overlay preview layer
- add apply-to-all overlay action

### Slice 4: Transitions

- add transition picker
- insert transition between selected scene and next scene
- add apply-all and random mix
- show transition track state

### Slice 5: Icons

- add icon picker
- create icon timeline item
- drag/resize icon on canvas
- adjust icon timing on timeline

### Slice 6: Render Compatibility

- map Studio creative controls to render data
- prepare FFmpeg/ASS overlay command builder
- add export tests after preview behavior is stable

