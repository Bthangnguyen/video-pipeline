# 06 Trim Selection And Render Assembly Flow

Status: proposed next implementation.

## Goal

Define how approved/downloaded materials become scene clips that match the voiceover duration, show word-synced text, preview audio/music/effects in Studio, and later render into a final MP4.

V1 decision:

```text
Manual trim selection is the primary flow.
MoneyPrinterTurbo-style auto-start cutting is the fallback/default.
No unstable "best moment" scoring is required.
```

## Why This Exists

The current Studio can place a whole raw video on the timeline. That is not enough for production because each scene needs:

- a clip duration that exactly matches the scene TTS duration
- user control over which part of the raw video is used
- text that appears in sync with the spoken words
- previewable overlays, background music, visual transforms, and transitions
- persisted decisions so the project can be resumed without losing candidate choices

MoneyPrinterTurbo is useful as a reference for duration matching, but it does not solve "choose the best visual moment" with AI. Its practical behavior is closer to:

- derive target duration from audio
- cut available source clips into duration-limited segments
- concatenate or loop enough visual duration to match audio
- generate subtitles from TTS timing data

For this product, visual choice should be user-led first.

## Required Inputs

Each scene should have:

```json
{
  "scene_id": "scn_001",
  "voiceover_text": "It is not about luck.",
  "on_screen_text": "It is not about luck.",
  "tts": {
    "audio_asset_id": "tts_001",
    "duration_seconds": 2.85,
    "word_timings": []
  },
  "material_asset_id": "mat_001"
}
```

Each material asset should have:

```json
{
  "asset_id": "mat_001",
  "source": "douyin",
  "local_path": "storage/videodesign/vdp_001/materials/scn_001.mp4",
  "duration_seconds": 11.2,
  "width": 1080,
  "height": 1920
}
```

## Output Scene Clip

After trim selection, the scene owns a production clip:

```json
{
  "scene_id": "scn_001",
  "clip": {
    "material_asset_id": "mat_001",
    "trim_source": "manual",
    "trim_start_seconds": 3.4,
    "trim_end_seconds": 6.25,
    "duration_seconds": 2.85,
    "fit": "cover",
    "loop_mode": "none",
    "transform": {
      "flip_horizontal": false,
      "crop_x": 50,
      "crop_y": 50,
      "zoom": 1,
      "rotation": 0
    },
    "effects": {
      "brightness": 1,
      "contrast": 1,
      "saturation": 1,
      "sharpness": 0
    },
    "transition": {
      "in": "none",
      "out": "fade",
      "duration_seconds": 0.25
    }
  }
}
```

`clip.duration_seconds` must equal the final TTS scene duration. If the TTS is regenerated and duration changes, the clip becomes `trim_stale` until it is confirmed again or auto-adjusted.

## Flow A: Manual Trim Selection

Manual trim is the main user experience.

### Entry Point

In Studio, selecting a scene media clip opens the Media tool panel.

The panel shows:

- approved material thumbnail
- source badge: Douyin or Pinterest
- raw video duration
- TTS scene duration
- `Select segment` button
- current trim start/end if already confirmed

### Trim Modal Or Panel

The trim editor contains:

- raw video player
- 9:16 preview frame
- timeline ruler for the raw video
- fixed-width trim window equal to `tts.duration_seconds`
- draggable trim window
- optional fine controls for start time
- `Play selected segment`
- `Confirm segment`
- `Use auto-start`

The window length is fixed because the scene duration comes from TTS.

### Interaction Rules

- Dragging the trim window updates `trim_start_seconds`.
- `trim_end_seconds = trim_start_seconds + tts.duration_seconds`.
- The window cannot move before `0`.
- The window cannot move after `asset.duration_seconds - tts.duration_seconds`.
- Clicking the raw video ruler seeks the player.
- `Play selected segment` seeks to trim start and stops at trim end.
- `Confirm segment` persists the clip to the project store.
- If the asset is shorter than TTS duration, use fallback handling.

### Short Asset Handling

If `asset.duration_seconds < tts.duration_seconds`, the UI marks the clip as short and offers:

```text
Loop clip
Freeze last frame
Replace material
```

V1 default:

```text
Loop clip
```

Persisted clip example:

```json
{
  "trim_start_seconds": 0,
  "trim_end_seconds": 1.8,
  "duration_seconds": 2.85,
  "loop_mode": "loop_to_fill",
  "trim_source": "manual_short_loop"
}
```

### API

Patch scene trim:

```text
PATCH /api/videodesign/projects/{project_id}/scenes/{scene_id}/clip
```

Request:

```json
{
  "material_asset_id": "mat_001",
  "trim_source": "manual",
  "trim_start_seconds": 3.4,
  "loop_mode": "none",
  "transform": {
    "flip_horizontal": false,
    "crop_x": 50,
    "crop_y": 50,
    "zoom": 1
  },
  "effects": {
    "brightness": 1,
    "contrast": 1.08,
    "saturation": 0.95,
    "sharpness": 0
  },
  "transition": {
    "out": "fade",
    "duration_seconds": 0.25
  }
}
```

Backend derives:

- `trim_end_seconds`
- `duration_seconds`
- stale/valid status

Validation:

- scene exists
- material asset exists and belongs to project
- TTS duration exists
- start/end stay inside raw asset, unless `loop_mode` handles short asset
- transform/effects are within safe numeric ranges

### Acceptance Criteria

- User can select a scene and open its raw video in the trim editor.
- User can drag a fixed-duration trim window.
- Playback starts at selected trim start and stops at selected trim end.
- Confirmed trim persists across page reload and Redis/project reload.
- Studio timeline uses only the selected segment, not the whole raw video.
- Regenerating TTS marks existing trims stale if duration changed.

## Flow B: MoneyPrinterTurbo-Style Auto Start Fallback

This is the fallback when the user has not manually selected a segment yet.

### Use Cases

- first timeline creation
- batch preview before manual refinement
- user clicks `Use auto-start`
- project needs a deterministic default without guessing visual quality

### Algorithm

For each scene:

```text
target_duration = scene.tts.duration_seconds
asset_duration = material_asset.duration_seconds

if asset_duration >= target_duration:
    trim_start = 0
    trim_end = target_duration
    loop_mode = none
else:
    trim_start = 0
    trim_end = asset_duration
    loop_mode = loop_to_fill
```

Persist:

```json
{
  "trim_source": "auto_start",
  "trim_start_seconds": 0,
  "trim_end_seconds": 2.85,
  "duration_seconds": 2.85,
  "loop_mode": "none"
}
```

### Differences From MoneyPrinterTurbo

MoneyPrinterTurbo can combine clips globally to match one audio file. This project is scene-based:

- one scene maps to one TTS duration
- each scene has one approved material asset
- auto-start is applied per scene
- the user can later override any scene manually

### Acceptance Criteria

- Creating Studio timeline works even if no manual trims exist.
- Every scene receives a deterministic clip.
- Timeline total duration equals the sum of scene TTS durations.
- Auto-start clips are visibly marked so the user knows they were not manually selected.

## Word-Synced Text

The product goal is word-level text matching the voice, not just one caption block per sentence.

### Preferred TTS Timing Data

Store word timings per scene:

```json
{
  "word": "luck",
  "start_seconds": 1.92,
  "end_seconds": 2.32,
  "index": 5,
  "text_range": [19, 23]
}
```

### Timing Sources

Priority:

1. TTS provider word boundaries, if available.
2. TTS provider sentence/segment timing plus proportional word split.
3. Local proportional fallback from total scene duration.

The fallback is acceptable for preview, but it should be marked:

```json
{
  "timing_quality": "estimated"
}
```

### Preview Behavior

During Studio playback:

- active scene is determined from playhead time
- local scene time controls voiceover and captions
- current word is highlighted using `word_timings`
- caption style comes from selected template preset

Example overlay state:

```json
{
  "caption_style_id": "bold_center_word_highlight",
  "active_word_index": 5,
  "text": "It is not about luck."
}
```

## Preview Assembly

The Studio preview should be browser-native before final render exists.

### Media Preview

For the active scene:

```text
video.currentTime = clip.trim_start_seconds + local_scene_time
```

If the clip loops:

```text
video.currentTime = clip.trim_start_seconds + (local_scene_time % clip_raw_duration)
```

### Audio Preview

Tracks:

- scene TTS audio
- optional project background music

Rules:

- TTS follows local scene time.
- Background music follows global timeline time.
- BGM default volume should be low, for example `0.12`.
- Muting BGM must not mute TTS.

### Visual Effects Preview

Use CSS for browser preview:

```css
transform: scaleX(-1) scale(1.02);
filter: brightness(1.02) contrast(1.08) saturate(0.95);
```

Effects needed in UI:

- flip horizontal
- brightness
- contrast
- saturation
- zoom/crop position

Avoid presenting these as copyright bypass guarantees. They are creative adjustment controls.

### Transition Preview

V1 supported transitions:

- none
- fade
- slide left
- zoom in

Browser preview can approximate transitions with CSS opacity/transform in the first or last `transition.duration_seconds` of a scene.

## Render Assembly Design

Final export can be implemented after preview is stable.

### FFmpeg Responsibilities

For each scene:

- cut raw material using `trim_start_seconds` and `duration_seconds`
- scale/crop to project aspect ratio
- apply hflip and color effects
- match clip duration to TTS
- burn captions/text overlays
- mix voiceover and BGM
- apply transitions between rendered scene clips

### Render Command Concepts

Clip cut:

```text
ffmpeg -ss {trim_start} -i material.mp4 -t {scene_duration}
```

9:16 fit:

```text
scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920
```

Effects:

```text
hflip,eq=brightness=0.02:contrast=1.08:saturation=0.95
```

Transitions:

```text
xfade=transition=fade:duration=0.25:offset={offset}
```

Caption rendering should prefer ASS subtitles or a rendered transparent overlay track, because word-level animation is difficult to express cleanly with simple SRT.

## Studio UI Additions

### Media Tool Panel

Add:

- trim status badge: `Auto`, `Manual`, `Stale`, `Short`
- `Select segment`
- flip toggle
- brightness slider
- contrast slider
- saturation slider
- crop/zoom controls
- transition picker

### Timeline

Media clip label:

```text
Scene 1 | 2.85s | Manual trim 3.40s-6.25s
```

Auto-start label:

```text
Scene 1 | 2.85s | Auto-start
```

### Preview Canvas

Show:

- selected media segment
- active word text
- text overlays
- icons/overlays
- transition preview when playhead enters transition range

## Project Status Values

Scene clip status:

```text
no_material
tts_missing
trim_missing
trim_auto
trim_manual
trim_stale
render_ready
```

Project render readiness:

```text
ready only when every non-placeholder scene has:
- material asset
- TTS duration
- clip trim
- caption timing
```

## Implementation Plan

### Slice 1: Data And Manual Trim

- add clip fields to scene model
- add API to patch scene clip
- derive auto-start clip when creating timeline
- add trim editor UI
- persist manual trim to project store

### Slice 2: Browser Preview

- make Studio play the selected trim segment, not the whole raw video
- sync TTS audio with the scene segment
- add BGM preview track
- preview flip/contrast/brightness/saturation

### Slice 3: Word-Synced Captions

- store word timings from TTS when available
- implement proportional fallback
- highlight current word in preview
- preserve template text style choices

### Slice 4: Transitions And Timeline Polish

- add transition picker
- preview basic transitions
- show stale trim warnings
- allow scene-by-scene manual correction

### Slice 5: Final Render

- build FFmpeg render graph
- cut material clips by trim
- mix TTS and BGM
- burn text/captions/overlays
- export MP4

## Test Plan

Unit/API:

- auto-start clip uses TTS duration when asset is long enough
- short asset uses `loop_to_fill`
- manual trim is clamped to valid raw video range
- TTS duration change marks manual clip as stale
- clip patch rejects another project's material asset
- word timing fallback fills scene duration

Frontend:

- dragging trim window seeks preview
- selected segment playback stops at trim end
- confirmed trim survives reload
- Studio preview shows only trimmed segment
- active word changes during playback
- flip/effects update preview without reloading page

Render later:

- FFmpeg command builder includes trim start/duration
- hflip/effects map to ffmpeg filters
- scene durations match TTS durations
- final timeline duration equals sum of scene durations

