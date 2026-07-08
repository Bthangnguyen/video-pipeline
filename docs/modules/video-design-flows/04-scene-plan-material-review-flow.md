# 04 Scene Plan And Material Review Flow

Status: draft.

Reference screenshots:

- `Screenshot 2026-07-06 215259.png`
- `Screenshot 2026-07-06 215317.png`

## Goal

Turn the approved script and preset into scene-level search tasks, then let the user approve which Douyin video will be used for each scene.

The user must see and control the scene-to-video mapping before Studio.

## Routes

Preferred future routes:

```text
/videodesign/{project_id}/plan
/videodesign/{project_id}/materials
```

They can be implemented as two tabs in one screen, but should feel like distinct workflow stages.

## Stage A: Scene Plan

### Purpose

Review and edit script segmentation before search.

### Layout

```text
left global rail | scene rail | selected scene editor | right project summary
```

Scene rail:

- scene number
- duration
- state badge
- first line of voiceover
- keyword count

Selected scene editor:

- voiceover text
- on-screen text
- visual brief
- matching keywords
- negative keywords
- duration estimate
- template scene assignment

Actions:

- split scene
- merge with previous
- merge with next
- save scene
- generate TTS timing for selected scene

### Scene Parsing Rules

Current rules remain:

- line breaks are strong boundaries in manual mode
- normal/dense use sentences as primary beats
- sparse merges short sentences around target duration
- max words per scene only splits overlong sentences

### Data

Scene fields:

```json
{
  "scene_id": "scn_001",
  "order": 1,
  "voiceover_text": "",
  "tts_text": "",
  "on_screen_text": "",
  "visual_brief": "",
  "matching_keywords": [],
  "negative_keywords": [],
  "duration_seconds": 4.0,
  "approval_state": "planned"
}
```

### Stale State

If user edits `voiceover_text` after TTS generation:

- set `tts.sync_state = stale`
- show `Regenerate timing`
- block Studio if captions/audio are stale and captions are enabled

V2 can start by showing the warning without blocking.

## Stage B: Material Search

### Purpose

Search Douyin per scene and propose candidates.

### Layout

```text
left scene rail | candidate review grid | right search/progress panel
```

Scene rail states:

- planned
- searching
- needs review
- approved
- downloaded
- placeholder
- failed

Candidate review grid:

- primary proposal large card
- alternative cards
- video preview button
- cover image
- title
- author
- duration
- source
- search keyword used
- approve/reject buttons

Right search panel:

- current keyword
- manual keyword input
- translate toggle
- candidates per scene
- button: `Search this scene`
- button: `Search all remaining`
- progress log

## Search Behavior

Default UI behavior:

1. User selects one scene.
2. User clicks `Search this scene`.
3. Backend runs DouyinSearch for that scene's keywords.
4. Results appear in candidate grid.
5. User approves one candidate.
6. User downloads approved video or continues approving more scenes.

Batch search can exist as a secondary action.

Important rule:

```text
The UI should not force a full-project Douyin search when the user only wants to retry one scene.
```

## API Requirements

Existing batch endpoint:

```text
POST /api/videodesign/projects/{project_id}/materials/search
```

Recommended new per-scene endpoint:

```text
POST /api/videodesign/projects/{project_id}/scenes/{scene_id}/materials/search
```

Request:

```json
{
  "keyword": "funny cat staring at wall",
  "candidates_per_scene": 4,
  "translate_to_chinese": true
}
```

Response:

```json
{
  "success": true,
  "scene": {},
  "candidates": []
}
```

Reuse existing selection endpoint:

```text
PATCH /api/videodesign/projects/{project_id}/scenes/{scene_id}/selection
```

Download:

```text
POST /api/videodesign/projects/{project_id}/materials/download
```

## Candidate Ranking

The module should not assign a quality score to video candidates. Candidate quality is too unstable without video understanding, so the product should focus on generating better search keywords and making preview/approval fast.

Each candidate should show:

- source
- search keyword used
- title/author/duration when available
- inline preview

## Approval Rules

Scene can enter Studio only if:

- `approval_state = downloaded`, or
- `approval_state = placeholder_allowed`

Scene candidate states:

- proposed
- approved
- rejected

When user approves a candidate:

- mark candidate as approved
- set `scene.selected_candidate_id`
- set `scene.approval_state = approved`

When user downloads:

- create `MaterialAsset`
- set `scene.material_asset_id`
- set `scene.approval_state = downloaded`

## Empty And Error States

No candidates:

- show `No candidates yet`
- show search controls

Search timeout:

- show `Search timed out for this keyword`
- allow retry with another keyword

Cookie/login issue:

- show typed DouyinSearch error
- link/button to `Check Douyin session`

Expired result during download:

- show `Result expired - search this scene again`

## Progress

For batch search:

- show current scene number
- current keyword
- completed/total scenes
- last error if any

For per-scene search:

- progress can be local to the scene card

## Acceptance Criteria

- User can inspect scenes before any Douyin search.
- User can edit scene text and keywords.
- User can search one scene at a time.
- User can batch search remaining scenes with visible progress.
- User can approve one candidate per scene.
- User can download only approved videos.
- Downloaded videos become local `MaterialAsset` records.
- Studio is blocked until each scene is downloaded or marked placeholder.
