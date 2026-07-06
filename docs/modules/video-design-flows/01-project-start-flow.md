# 01 Project Start Flow

Status: draft.

Reference screenshots:

- `Screenshot 2026-07-06 214433.png`
- `Screenshot 2026-07-06 215243.png`

## Goal

Give the user one obvious place to start a video project from an idea or script, with only the minimum setup needed before moving into Script Creation.

This screen should feel like the first Fliki prompt screen: calm, direct, and centered.

## Entry Points

- `/videodesign`
- `New video` button from future project list
- `Create from Douyin result` later

## Layout

```text
left icon rail | centered create panel | optional recent projects
```

### Left Icon Rail

Purpose: stable navigation, copied from the reference app.

Items:

- Home
- Projects
- Douyin Search
- Templates
- Studio
- Settings

Only Home and Douyin Search need to be active in V1. Other items can be disabled placeholders if implementation needs to stay small.

### Create Panel

Fields:

- `idea_or_script`: large textarea
- `target_duration_seconds`: slider plus numeric label
- `target_platform`: TikTok/Douyin, Shorts, Reels
- optional `reference_material`: placeholder attachment row, not functional in this slice

Primary CTA:

- `Create video`

Secondary CTA:

- `Open existing project` from project id or recent project list

## User Flow

1. User enters a short idea or full script.
2. User adjusts target duration.
3. User clicks `Create video`.
4. Backend creates `VideoDesignProject`.
5. App navigates to Script Creation flow.

## Behavior

If input looks like a short idea:

- create project with `script_source = deepseek_pending`
- set `idea`
- leave `script` empty
- next screen highlights `Generate script`

If input looks like a longer script:

- create project with `script_source = user`
- set `script`
- next screen highlights `Use current script`

Heuristic for first implementation:

```text
word_count < 35 -> idea
word_count >= 35 -> script
```

This heuristic should be visible only through behavior, not explained in the UI.

## Data

Create request:

```json
{
  "idea": "cat facts for a short video",
  "script": null,
  "target_platform": "tiktok",
  "aspect_ratio": "9:16",
  "target_duration_seconds": 45,
  "language": "en",
  "style_brief": ""
}
```

Persisted state:

- `project_id`
- `idea`
- `script`
- `target_platform`
- `target_duration_seconds`
- `created_at`

## Empty States

No recent projects:

- show a compact empty row: `No saved projects yet`

Create input empty:

- keep CTA disabled
- do not show an error until user tries to submit

## Success Criteria

- User can start with one prompt and one CTA.
- User does not see scene settings, Douyin settings, or Studio controls on this screen.
- Project is persisted immediately to `storage/videodesign/{project_id}/project.json`.
- App can reload the project by id after creation.

