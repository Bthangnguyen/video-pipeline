# 05 Studio Timeline Flow

Status: draft, high priority.

Reference screenshot:

- `Screenshot 2026-07-06 214613.png`

## Goal

Turn approved/downloaded scene materials into a visual editing workspace where the user can preview scenes, inspect layers, and adjust timing/position before a future render module exports MP4.

Studio must feel like an editor, not a JSON viewer.

## Route

Preferred future route:

```text
/videodesign/{project_id}/studio
```

## Required Precondition

Every non-placeholder scene must have:

- `scene.material_asset_id`
- local material file available through `/materials/{asset_id}/file`

Placeholder scenes can be allowed, but should appear visually distinct in the timeline.

## Layout

Copied from reference Studio:

```text
top action bar
left tool rail | left active tool panel | preview canvas
bottom timeline
```

### Top Action Bar

Items:

- project title
- save indicator
- undo placeholder
- redo placeholder
- more menu placeholder
- preview/play button
- export/download disabled until render module exists

Recommended copy:

```text
Export disabled - render module not implemented yet
```

### Left Tool Rail

Tools:

- Script
- Media
- Text
- Captions
- Audio
- Icons
- Settings

Only Script, Media, Text, Captions, and Settings need V2 behavior. Icons can be implemented as timeline data with a simple picker later.

### Active Tool Panel

Panel changes based on selected rail item.

Script panel:

- scene list
- thumbnail
- voiceover text
- on-screen text
- selected state
- add scene placeholder disabled for V2

Media panel:

- selected scene material
- preview candidate/source
- replace material button links back to Material Review

Text panel:

- selected text overlay
- text input
- position controls
- scale
- rotation
- timing start/end

Captions panel:

- caption style
- position
- caption chunks for selected scene
- regenerate timing button if stale

Settings panel:

- aspect ratio
- timeline duration
- layer visibility toggles

### Preview Canvas

Canvas area:

- 9:16 phone preview by default
- loaded local material video
- caption overlay
- text overlay
- icon/shape overlays later
- selected overlay handles

Preview controls:

- play/pause
- current time
- scene selector
- fit/zoom preview

V2 canvas interaction:

- click text overlay to select
- drag text overlay within preview
- update `TimelineItem.transform.x` and `TimelineItem.transform.y`
- clamp x/y to 0-100 percent

### Timeline

Tracks:

```text
media_base
caption_default
text_overlay
icon
voiceover_audio
background_audio
transition
```

V2 minimum tracks:

- media_base
- caption_default
- text_overlay
- voiceover_audio

Timeline elements:

- playhead
- time ruler
- zoom controls
- horizontal scroll
- selected clip outline
- scene labels

Clip visual rules:

- media clips: thumbnail blocks
- caption clips: green or pink text blocks
- text clips: purple text blocks
- audio clips: teal waveform placeholder
- placeholder scenes: dashed border

## Selection Model

Global selected state:

```json
{
  "selected_scene_id": "scn_001",
  "selected_item_id": "itm_001",
  "selected_tool": "Script",
  "playhead_seconds": 0
}
```

Clicking a scene in Script panel:

- sets selected scene
- loads scene media into preview
- highlights all timeline items for scene

Clicking a timeline item:

- sets selected item
- sets selected scene
- opens relevant tool panel
  - media -> Media
  - text -> Text
  - caption -> Captions
  - audio -> Audio

Clicking a canvas text overlay:

- selects corresponding text item
- opens Text panel

## Timeline Drag Behavior

### Drag Media Clip

Purpose: adjust where a media scene starts in the timeline.

Rules:

- drag horizontally changes `start_seconds` and `end_seconds` by the same delta
- clip duration stays the same
- do not allow negative start
- snap to scene boundaries and 0.1 second increments
- if moving creates overlap, either:
  - prevent the move, or
  - push adjacent clips later

V2 should choose the simpler rule:

```text
prevent overlap and show snap boundary
```

### Resize Media Clip

Purpose: adjust scene timing.

Rules:

- left edge changes `start_seconds`
- right edge changes `end_seconds`
- minimum duration: 0.5s
- caption/text/audio items in the same scene should either:
  - resize with scene, or
  - show stale timing warning

V2 simpler rule:

```text
resize media scene and keep caption/text within scene bounds.
```

### Drag Text Clip

Purpose: change when text appears.

Rules:

- drag horizontally changes start/end
- text clip cannot leave its scene media bounds unless user holds future advanced modifier
- minimum duration: 0.3s

### Resize Text Clip

Rules:

- adjust start/end
- clamp to scene media bounds

## Canvas Drag Behavior

### Drag Text Overlay

Input:

- pointer down on selected text overlay
- move inside preview bounds

Output:

```json
{
  "transform": {
    "x": 52,
    "y": 18,
    "scale": 1,
    "rotation": 0
  }
}
```

Coordinates:

- x/y are percentages of preview size
- center point of overlay
- clamp 0-100

Persist:

```text
PATCH /api/videodesign/projects/{project_id}/timeline/items/{item_id}
```

Request:

```json
{
  "transform": {
    "x": 52,
    "y": 18,
    "scale": 1,
    "rotation": 0
  }
}
```

## Timeline Patch API

Existing endpoint:

```text
PATCH /api/videodesign/projects/{project_id}/timeline/items/{item_id}
```

Supported request:

```json
{
  "start_seconds": 1.2,
  "end_seconds": 3.8,
  "transform": {
    "x": 50,
    "y": 20,
    "scale": 1,
    "rotation": 0
  },
  "style": {
    "caption_style_id": "bold_outline"
  }
}
```

Needed backend validation:

- `end_seconds > start_seconds`
- start/end cannot be negative
- text/caption item stays within parent scene bounds
- transform values are numeric and within safe ranges

V2 can implement frontend validation first, then backend hardening.

## Playback Model

V2 playback can be scene-based, not full-render accurate.

When playhead enters a media item:

- load corresponding media URL
- seek local video to approximate scene offset if possible
- show caption/text items active at playhead time

Minimum acceptable behavior:

- click scene -> preview scene video
- play button plays current scene video
- playhead position updates inside the current scene

Full timeline playback can come later.

## Data Model

Timeline item examples:

Media:

```json
{
  "item_id": "itm_media_001",
  "layer_id": "media_base",
  "scene_id": "scn_001",
  "type": "media",
  "start_seconds": 0,
  "end_seconds": 4.2,
  "source_ref": {
    "source": "material_asset",
    "asset_id": "mat_001",
    "media_url": "/api/videodesign/projects/vdp_001/materials/mat_001/file"
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

Text:

```json
{
  "item_id": "itm_text_001",
  "layer_id": "text_overlay",
  "scene_id": "scn_001",
  "type": "text",
  "start_seconds": 0.2,
  "end_seconds": 2.8,
  "source_ref": {
    "text": "Cats know your voice"
  },
  "transform": {
    "x": 50,
    "y": 18,
    "scale": 1,
    "rotation": 0
  },
  "style": {
    "font_size": 48,
    "color": "#ffffff",
    "shadow": true
  }
}
```

Icon later:

```json
{
  "item_id": "itm_icon_001",
  "layer_id": "icon",
  "scene_id": "scn_001",
  "type": "icon",
  "start_seconds": 1.0,
  "end_seconds": 3.0,
  "source_ref": {
    "icon": "arrow-right"
  },
  "transform": {
    "x": 62,
    "y": 38,
    "scale": 1,
    "rotation": -12
  },
  "style": {
    "color": "#ffffff",
    "shadow": true
  }
}
```

## UI States

No timeline:

- show CTA: `Create Studio Timeline`
- explain which scenes still need downloaded media

Missing media file:

- show placeholder block
- show `Material file missing`
- action: `Return to materials`

Selected item:

- outline timeline clip
- show handles on canvas if visual item
- open matching tool panel

Unsaved drag:

- optimistic update in UI
- debounce PATCH after drag end
- if PATCH fails, revert and show error

## Keyboard Shortcuts Later

Not required in V2, but leave room for:

- Space: play/pause
- Delete: remove selected overlay
- Arrow keys: nudge selected overlay
- Ctrl+Z: undo
- Ctrl+Y: redo

## Acceptance Criteria

- Studio opens from a downloaded project.
- User sees a tool rail, active tool panel, preview canvas, and bottom timeline.
- User can select scenes from the Script panel.
- User can click timeline clips to select related items.
- Preview video changes when selected scene changes.
- Captions and text overlays appear on the preview canvas.
- Timeline shows at least media, caption, text, and audio layers.
- User can drag a text overlay on the preview canvas and persist transform.
- User can drag/resize a text timing block and persist start/end.
- User can drag/resize a media block with overlap prevention.
- Project timeline changes persist to `project.json`.
- Existing tests remain green.

## Implementation Scope Recommendation

First implementation slice:

1. Rebuild Studio layout to match reference.
2. Add item selection model.
3. Add canvas text dragging.
4. Add timeline text clip drag/resize.
5. Add media clip drag/resize only after text works.

This order keeps the hardest UI behavior isolated before touching scene-level media timing.

