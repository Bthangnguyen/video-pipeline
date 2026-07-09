# 09 Studio Transition, Caption Drag, And Playhead Flow

Status: proposed next implementation.

## Goal

Make Studio preview feel like a real editor:

- scene transitions should not jump, flash black, or briefly show the wrong scene
- captions should be draggable on the video canvas, with style controls and apply-to-all
- the timeline playhead should be draggable for fast random-time preview

This spec is based on the current product issues plus a focused review of `D:\Workspaces\automation videos\MoneyPrinterTurbo`.

## Current Problems

Transition preview:

- simple fades can work because they only need opacity changes
- slide, push, zoom, and shuffle transitions can stutter because the next video is not guaranteed to be loaded and seeked before the boundary
- switching `<video src>` at the boundary can show a black frame, an old frame, or a frame from the wrong scene
- browser preview and final render do not yet share the same transition model

Caption editing:

- text overlays are draggable, but caption overlays are not yet treated as first-class draggable canvas items
- caption position/style edits do not have a clear `current scene` vs `all scenes` scope
- active word emphasis needs better controls, especially glow intensity/blur/color

Playhead:

- timeline click seek exists, but the playhead itself is not a scrub handle
- random-time review is slow because the user cannot drag the playhead and immediately see the corresponding video/caption state

## MoneyPrinterTurbo Transition Findings

Relevant files:

- `D:\Workspaces\automation videos\MoneyPrinterTurbo\app\services\video.py`
- `D:\Workspaces\automation videos\MoneyPrinterTurbo\app\services\utils\video_effects.py`
- `D:\Workspaces\automation videos\MoneyPrinterTurbo\app\controllers\v1\studio.py`
- `D:\Workspaces\automation videos\MoneyPrinterTurbo\app\models\schema.py`

What it does well:

- uses audio duration as the target visual duration
- splits source videos into short subclips using `max_clip_duration`
- normalizes each visual clip to the target aspect ratio/resolution
- renders each processed clip/segment to an intermediate MP4
- concatenates prepared MP4 files with FFmpeg instead of asking the browser to switch raw clips in realtime
- concatenates voice audio and offsets subtitles by cumulative audio time
- mixes BGM and burns subtitles after the visual track and voice track are assembled

Transition model found:

- transition enum is limited to `None`, `Shuffle`, `FadeIn`, `FadeOut`, `SlideIn`, `SlideOut`
- `FadeIn` and `FadeOut` use MoviePy `vfx.FadeIn` / `vfx.FadeOut`
- slide transitions are implemented as a black background plus a moving clip inside `CompositeVideoClip`
- each transitioned clip is rendered to a temp MP4 first
- final assembly uses FFmpeg concat over those temp MP4 files

Important limitation:

- MoneyPrinterTurbo transitions are mostly per-clip entrance/exit effects, not true two-clip overlap transitions
- it does not solve browser realtime preview directly
- its slide implementation intentionally uses a black background, which explains why copying it directly can still produce black-frame-looking transitions

Decision for this project:

- use MoneyPrinterTurbo's stable render architecture: normalize -> render intermediate clips -> concat/mix audio
- do not copy its transition behavior as-is for Studio preview
- final target should use dual-buffer browser preview and FFmpeg overlap transitions for export

## Proposed Solution

### 1. Smooth Studio Transition Preview

Use dual video buffers:

- `currentVideo`: scene currently visible
- `nextVideo`: next scene preloaded before transition starts
- preload starts at `transition.start_seconds - preload_margin`
- preload margin default: `0.5s`
- set `nextVideo.src` and seek it to its `trim_start_seconds` before the transition window
- only run complex transition if `nextVideo.readyState >= HAVE_CURRENT_DATA`
- otherwise fallback to `crossfade` or `hard_cut`

Allowed realtime transition set for V1:

- `hard_cut`
- `crossfade`
- `fade`
- `zoom_crossfade`
- `slide_crossfade`

Hold these until after dual-buffer is stable:

- `whip_pan`
- `push_slide`
- random/mix transitions
- transitions that require rapid seek/source switching

Implementation rules:

- global voiceover remains the source of truth
- transition preview reads from `audio.currentTime`, not `video.currentTime`
- video can lag and resync, but audio must never be reset at scene boundaries
- no transition should create a black background unless user explicitly chooses a black fade style

Acceptance criteria:

- play through 5 scenes with global TTS and no audio cut
- transition boundary does not show a black frame
- transition boundary does not show a stale frame from a previous scene
- if next video is not ready, preview falls back cleanly instead of glitching

### 2. Preview Proxy For Material Assets

Create a normalized preview proxy after material download or before Studio:

```text
input material -> ffmpeg proxy -> storage/videodesign/{project_id}/proxies/{asset_id}.mp4
```

Proxy format:

- MP4
- H.264
- 30 fps
- 1080x1920 for 9:16 projects
- `yuv420p`
- faststart
- consistent keyframe interval
- audio removed or ignored for Studio preview

Why:

- raw Douyin/Pinterest files can have inconsistent codecs, frame rates, keyframes, and streaming metadata
- seeking raw files causes most scrub/transition stutter
- a predictable proxy makes playhead drag and transition preview much more stable

Acceptance criteria:

- Studio media uses proxy URL when available
- scrub to random time updates video within roughly `0.3-0.5s`
- transition preview uses proxy files, not raw downloaded files

### 3. Final Render Transition Model

For export/render, use FFmpeg overlap transitions instead of browser CSS approximation:

- use global voiceover duration as the final timeline duration
- scene visual clips are cut to match voiceover offsets
- overlap neighboring clips by transition duration
- use FFmpeg `xfade` for supported transitions
- use `acrossfade` or keep global voiceover untouched; do not split voiceover by scene
- overlays, captions, icons, and BGM are applied after the base visual timeline is assembled

Supported render transitions V1:

- `fade`
- `wipeleft`
- `wiperight`
- `slideleft`
- `slideright`
- `circleopen` only if stable

Fallback:

- unsupported transition -> `fade`
- transition duration longer than scene duration -> clamp to safe duration

Acceptance criteria:

- rendered output has no visible hard black gaps between scenes
- rendered transition duration matches Studio timeline metadata
- audio is one continuous voiceover track from start to end

### 4. Draggable Caption Canvas

Treat caption as a real draggable canvas item, like text/icon:

- `caption.transform.x`
- `caption.transform.y`
- `caption.transform.scale`
- `caption.transform.rotation`

Canvas behavior:

- pointer down on caption starts drag
- drag updates selected caption item transform
- preview updates immediately
- save persists transform into timeline item

Inspector controls:

- font family
- font size
- weight
- text color
- active word color
- stroke color/width
- shadow on/off
- glow on/off
- glow color
- glow blur
- glow intensity
- apply scope: `current scene` or `all scenes`

Active word glow:

```text
inactive words: normal caption style
active word: active color + stroke + glow text-shadow
```

Acceptance criteria:

- user can drag caption directly on the video
- user can apply caption position/style to all scenes
- active word glow is visible without making inactive words unreadable

### 5. Draggable Timeline Playhead

Make the playhead itself a pointer target:

- pointer down on playhead starts scrub
- remember whether playback was active
- pause audio/video while dragging
- while dragging, set global time from pointer position
- seek global audio to that time
- select current scene/media based on that time
- seek current video to `trim_start_seconds + local_scene_time`
- update captions, transitions, overlays, and icons immediately
- on pointer up, resume playback if it was playing before drag

Rules:

- when global voiceover exists, scrub time comes from the voiceover timeline
- when global voiceover does not exist, scrub falls back to video-driven preview
- playhead drag should not modify timeline item timing; it only changes preview time

Acceptance criteria:

- user can drag playhead to any time and see the matching scene
- captions update while dragging
- transition preview updates inside transition windows
- release resumes playback only if playback was active before drag

## Implementation Order

1. Add preview proxy generation and prefer proxy media in Studio.
2. Rework transition preview to dual-buffer with safe fallbacks.
3. Add draggable playhead scrub.
4. Add draggable caption transform.
5. Add caption style scope controls and active-word glow.
6. Add final render transition mapping with FFmpeg `xfade`.

## Non-Goals For This Pass

- no AI video quality scoring
- no automatic best-shot selection
- no full export UI redesign
- no transition marketplace or large preset library
- no frame-perfect browser compositor

## Notes For Current Codebase

- Global TTS is now the correct source of truth for time.
- Studio preview should continue reading `audio.currentTime` as the primary playhead.
- Current transition code should be treated as a visual approximation until dual-buffer/proxy exists.
- MoneyPrinterTurbo is a strong reference for stable preprocessing and render assembly, but not for realtime Studio transition UX.
