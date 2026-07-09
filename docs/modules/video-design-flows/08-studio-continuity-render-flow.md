# 08 Studio Continuity And Render Flow

Status: proposed next implementation.

## Goal

Remove the unnatural pauses between scenes by making Studio playback and final render use one continuous production timeline.

This spec is based on the MoneyPrinterTurbo review, but does not copy its transition model directly. MoneyPrinterTurbo is useful for audio duration handling, clip preparation, subtitle offset aggregation, and stable FFmpeg output. For transitions, this project should go further and use real overlap/crossfade behavior instead of simple hard concat with per-clip fade effects.

## Problem

The current Studio preview can still feel choppy because it is scene-driven:

- video playback changes `<video src>` at scene boundaries
- voiceover playback changes `<audio src>` at scene boundaries
- TTS duration is estimated from text instead of measured from the generated audio file
- transition preview is a browser-side approximation, not the same model as final render
- there is not yet a final render pipeline that treats voiceover, BGM, captions, overlays, icons, and transitions as one timeline

The result is visible interruption:

```text
scene 1 video/audio -> source switch -> scene 2 video/audio
```

The desired behavior is:

```text
one global timeline clock
one continuous voiceover track
preloaded video layers around scene boundaries
rendered transitions with real overlap
```

## MoneyPrinterTurbo Findings

Useful patterns:

- Main task flow generates one full voiceover file for the whole script, then makes visual materials cover the audio duration.
- It measures real audio duration and adds a small visual safety margin so voiceover does not end on black or missing video.
- It preprocesses visual clips into normalized temp MP4 files, then concatenates with FFmpeg.
- Its studio flow can synthesize TTS per segment, then concatenate segment audio and offset subtitle timing by cumulative segment time.
- It burns subtitles and mixes BGM only after the silent video and voice track have been assembled.

Limitations:

- Its transition implementation is mostly per-clip fade/slide before concat.
- It does not use true two-clip overlap transitions like FFmpeg `xfade`.
- Copying that transition behavior would not fully solve the choppy boundary issue.

Decision:

```text
Use MoneyPrinterTurbo's timeline/audio/render structure.
Do not copy its transition implementation as the final target.
Use FFmpeg overlap transitions for final render.
```

## Design Principle

The production timeline is the source of truth.

Scene data remains useful for planning and editing, but playback/render should be driven by timeline items:

```text
global_time
-> active media items
-> active audio items
-> active caption words
-> active overlay/icon/text items
-> active transition window
```

Scene boundaries should not force a full media reload during playback.

## Phase 1: True TTS Timing

### Current Issue

The current Edge TTS path writes an audio file, but uses estimated text duration for:

- `scene.duration_seconds`
- `scene.caption_chunks`
- timeline media duration

This can make scene video shorter or longer than the real voiceover.

### Required Behavior

After TTS generation:

- measure the actual audio file duration
- store that real duration on the scene
- regenerate caption chunks from the real duration
- mark any existing manual clip as stale if the new audio duration changes significantly

### Target Data

```json
{
  "tts": {
    "provider": "edge_tts",
    "voice_id": "en-US-AriaNeural",
    "audio_path": "storage/videodesign/vdp_001/audio/scn_001.mp3",
    "audio_url": "/api/videodesign/projects/vdp_001/scenes/scn_001/audio",
    "duration_seconds": 2.74,
    "sync_state": "synced"
  },
  "caption_chunks": [
    {
      "text": "It",
      "start_seconds": 0.0,
      "end_seconds": 0.18
    }
  ]
}
```

### Acceptance Criteria

- A generated scene audio file reports the same duration in backend metadata and browser preview within `0.1s`.
- Timeline scene duration uses actual TTS duration.
- If TTS is regenerated, timeline media end times are recalculated or clip state becomes `trim_stale`.

## Phase 2: Combined Voiceover Track

### Current Issue

Studio uses one audio element for the selected scene. When playback crosses to the next scene, the browser must load and play a new audio file.

### Required Behavior

Build a combined voiceover asset for the project after scene TTS exists:

```text
scene 1 audio + scene 2 audio + scene 3 audio -> voiceover_combined.mp3
```

Store cumulative offsets:

```json
{
  "voiceover_track": {
    "audio_path": "storage/videodesign/vdp_001/audio/voiceover_combined.mp3",
    "audio_url": "/api/videodesign/projects/vdp_001/audio/combined",
    "duration_seconds": 31.42,
    "scene_offsets": [
      {
        "scene_id": "scn_001",
        "start_seconds": 0.0,
        "end_seconds": 2.74
      },
      {
        "scene_id": "scn_002",
        "start_seconds": 2.74,
        "end_seconds": 5.93
      }
    ]
  }
}
```

### Backend API

```text
POST /api/videodesign/projects/{project_id}/audio/combined
GET  /api/videodesign/projects/{project_id}/audio/combined
```

The `POST` endpoint should:

- validate every renderable scene has TTS audio
- concatenate scene audio in scene order
- update project timeline duration from the combined track
- rewrite caption chunk global offsets or keep scene-local chunks plus scene offset metadata

### Acceptance Criteria

- Studio can play the whole project with one audio element.
- Seeking to any timeline time seeks the combined audio to the same global time.
- Moving between scenes no longer changes audio `src`.

## Phase 3: Smooth Studio Preview Engine

### Current Issue

The current preview changes selected scene and rerenders the stage as playback crosses scene boundaries. This can trigger video source loading at exactly the moment the transition should be smooth.

### Required Behavior

Studio preview should use a small media pool:

```text
previous video layer
current video layer
next video layer
one combined audio layer
caption/text/icon/overlay layers driven by global time
```

During playback:

- keep the global clock running from `requestAnimationFrame`
- do not call full `renderStudio()` every frame
- preload next scene media before the transition window starts
- update the selected scene indicator without forcing media reload
- use the current and next video layers for transition preview

### Preview Transition Model

For preview, the browser should approximate final render:

- `fade` and `dissolve`: crossfade current and next layer opacity
- `slide_left/right/up`: move both layers during the transition window
- `zoom_in/out`: scale and crossfade both layers
- `flash_cut`: show flash overlay and swap layers at midpoint

### Non-goals

- Browser preview does not need frame-perfect parity with FFmpeg.
- Preview should be fast and interactive, not a full render.

### Acceptance Criteria

- Playback does not change video `src` at the exact transition boundary.
- Next scene video is loaded before the transition starts.
- Audio continues without restarting when the selected scene changes.

## Phase 4: Final Render Pipeline

### Goal

Produce a final MP4 from the Studio timeline with:

- trimmed scene videos
- continuous voiceover
- optional BGM
- captions/text/icons/overlays
- real video transitions

### Render Steps

```text
1. Validate timeline
2. Normalize each scene media clip
3. Build transition-aware video filter graph
4. Build continuous audio graph
5. Burn captions/text/icons/overlays
6. Write final MP4
7. Store render asset and preview URL
```

### Step 1: Validate Timeline

Required:

- every renderable scene has a downloaded `MaterialAsset`
- every renderable scene has TTS audio
- every scene has a clip trim that covers the scene duration
- transition duration does not exceed a safe fraction of either neighboring scene

Suggested validation:

```text
transition_duration <= min(0.75s, previous_scene_duration * 0.35, next_scene_duration * 0.35)
```

### Step 2: Normalize Scene Clips

For each media scene:

- input local material path
- apply trim start/end
- apply speed if configured
- scale/crop to project aspect ratio
- apply flip/brightness/contrast/saturation
- output a normalized silent clip

The output clip duration should match the scene TTS duration plus any required transition handles.

### Step 3: Real Transitions

Use FFmpeg overlap transitions for final render.

Conceptual model:

```text
scene 1: 0.00s -> 3.00s
transition: 2.65s -> 3.00s
scene 2 starts visually at 2.65s, not 3.00s
```

Transition mapping:

```json
{
  "fade": "xfade=transition=fade",
  "dissolve": "xfade=transition=dissolve",
  "slide_left": "xfade=transition=slideleft",
  "slide_right": "xfade=transition=slideright",
  "slide_up": "xfade=transition=slideup",
  "zoom_in": "xfade=transition=zoomin",
  "zoom_out": "xfade=transition=fade",
  "flash_cut": "custom flash overlay + hard cut fallback"
}
```

If a requested transition is not supported by the local FFmpeg build, fallback to `fade` and record a render warning.

### Step 4: Audio

Voiceover:

- use the combined voiceover track if available
- otherwise concatenate scene TTS files in timeline order

BGM:

- loop or trim to final duration
- lower volume independently from voiceover
- fade out near the end
- mix with voiceover using FFmpeg or MoviePy

Scene-level audio gaps:

- no gaps by default
- optional future setting: add deliberate pause between scenes

### Step 5: Captions And Overlays

Caption rendering should use global timing:

```text
scene local caption time + scene global offset = final caption time
```

V1 render support:

- one-word caption mode
- full-line caption mode
- text overlay
- static icon overlay
- scene overlay pack

Later render support:

- draggable animated icons
- richer text animation templates
- ASS subtitle styling for better text effects

### Backend API

```text
POST /api/videodesign/projects/{project_id}/render
GET  /api/videodesign/projects/{project_id}/render/progress
GET  /api/videodesign/projects/{project_id}/renders/{render_id}
GET  /api/videodesign/projects/{project_id}/renders/{render_id}/video
```

### Render Progress

```json
{
  "stage": "rendering_video",
  "message": "Applying transitions",
  "current": 3,
  "total": 7,
  "warnings": []
}
```

### Acceptance Criteria

- Final MP4 has no visible black frame between scenes.
- Voiceover plays continuously without file-boundary gaps.
- BGM continues across scenes and ends with fade-out.
- Captions appear at the correct global time.
- Render endpoint returns a playable final video URL.

## Phase 5: Preview And Render Parity

Studio preview does not need to be identical to final render, but the selected settings should mean the same thing.

Required parity:

- transition ID
- transition duration
- clip trim start/end
- flip/effects
- caption mode
- text/icon position

Allowed difference:

- browser preview may approximate effects
- final render is authoritative

## Data Model Additions

Project:

```json
{
  "voiceover_track": {
    "audio_path": "",
    "audio_url": "",
    "duration_seconds": 0,
    "scene_offsets": []
  },
  "renders": []
}
```

Timeline item:

```json
{
  "type": "transition",
  "source_ref": {
    "from_scene_id": "scn_001",
    "to_scene_id": "scn_002",
    "transition_id": "fade"
  },
  "style": {
    "duration_seconds": 0.35,
    "render_transition": "fade"
  }
}
```

Render asset:

```json
{
  "render_id": "rnd_001",
  "status": "complete",
  "local_path": "storage/videodesign/vdp_001/renders/final.mp4",
  "video_url": "/api/videodesign/projects/vdp_001/renders/rnd_001/video",
  "duration_seconds": 31.42,
  "warnings": []
}
```

## Implementation Order

1. Measure real TTS audio duration and regenerate caption chunks.
2. Add combined voiceover asset and API.
3. Update Studio preview to play one combined audio track.
4. Update video preview layer pool so next media is preloaded before transition.
5. Add render API with no transition first: normalized clips + continuous audio + captions.
6. Add FFmpeg `xfade` transitions for final render.
7. Align browser preview labels/settings with final render transition mappings.

This order keeps every step testable and avoids a large all-at-once render rewrite.

## Test Plan

Unit tests:

- TTS duration measurement from generated audio file
- combined voiceover scene offsets
- transition duration validation
- FFmpeg transition mapping fallback

API tests:

- combined voiceover endpoint requires TTS for all scenes
- render endpoint rejects missing material or stale clips
- render progress returns typed status
- render video endpoint streams final MP4

Frontend checks:

- Studio playback uses combined audio when available
- seeking timeline seeks combined audio to the same global time
- transition preview preloads next video before boundary
- scene selection changes do not restart audio

Manual acceptance:

- create a project with at least three scenes
- generate TTS
- approve/download one video per scene
- create timeline
- play across scene 1 -> scene 2 -> scene 3
- confirm no obvious audio restart at scene boundaries
- render final MP4
- confirm transitions are visible and voiceover is continuous

## Non-goals

- AI best-moment detection
- automatic copyright scoring
- multi-track advanced audio mixing beyond voiceover plus BGM
- frame-perfect browser preview
- cloud render queue

## Open Questions

- Should the product keep per-scene TTS generation for editability, then always combine audio for Studio playback?
- Should users be allowed to insert intentional pauses between scenes?
- Should transition handles extend clips by reusing adjacent video frames when the selected trim is too short?
- Should final render use MoviePy for overlays and FFmpeg for transition concat, or one FFmpeg graph for everything?

