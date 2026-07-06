# 02 Script Creation Flow

Status: draft, high priority.

Reference screenshots:

- `Screenshot 2026-07-06 215259.png`
- `Screenshot 2026-07-06 215243.png`

## Goal

Turn an idea or raw script into a clean, editable short-form video script before template selection, TTS, and Douyin search.

This flow must make the user feel in control of the script. DeepSeek helps generate and structure the script, but the user can edit before any downstream work begins.

## Route

Preferred future route:

```text
/videodesign/{project_id}/script
```

Temporary V1 route can remain:

```text
/videodesign?project_id={project_id}
```

## Layout

```text
left global rail | main script workspace | sticky right "Your video" summary rail
```

### Main Script Workspace

Top:

- title: `Script to Video`
- short subtitle: `Write or generate your script. Scene tags and visual notes guide material search.`
- project save indicator

Script card:

- card title: `Your script`
- helper text: `[Scene] and [Visual] tags guide the AI.`
- large textarea
- inline buttons:
  - `Generate with DeepSeek`
  - `Edit with AI`
  - `Use current script`
  - `Parse scenes`

Script quality strip:

- estimated duration
- word count
- estimated scene count
- language
- stale/synced state

### Right Summary Rail

Copied from the reference `Your video` rail.

Rows:

- Format
- Template
- Scene media
- Voiceover
- Captions
- Extras

During this flow, rows can show defaults:

```text
Format       Portrait 9:16
Template     No template
Scene media  Douyin stock
Voiceover    Auto voice - English
Captions     Bold Outline
Extras       2 of 5 enabled
```

Primary CTA:

- `Continue to template`

CTA disabled until:

- project has non-empty script
- script has been parsed or accepted

## Script Input Modes

### Mode A: Generate From Idea

Initial state when `project.script_source = deepseek_pending`.

UI:

- idea appears in compact prompt bubble
- textarea initially empty or contains placeholder
- primary action: `Generate with DeepSeek`

Backend:

```text
POST /api/videodesign/projects/{project_id}/script/generate
```

Request:

```json
{
  "idea": "cat facts explainer",
  "target_duration_seconds": 45,
  "tone": "short, engaging social video",
  "language": "en"
}
```

Expected DeepSeek output:

```json
{
  "title": "Cat Facts That Explain Everything",
  "hook": "Your cat is not random. It is running ancient software.",
  "script": "Ever wonder what your cat is really thinking...",
  "scenes": [
    {
      "voiceover_text": "Ever wonder what your cat is really thinking?",
      "on_screen_text": "What cats think",
      "visual_brief": "close-up cat staring at wall",
      "search_keywords": ["cat staring at wall", "funny cat close up"]
    }
  ]
}
```

After success:

- fill textarea with `script`
- if `scenes` exist, show preview scene count
- keep user on this screen
- show non-blocking toast: `Script generated`

### Mode B: User Script

Initial state when project already has `script`.

UI:

- textarea filled with script
- primary action: `Parse scenes`
- secondary action: `Edit with AI`

No DeepSeek call should happen unless user clicks `Generate` or `Edit with AI`.

### Mode C: Edit With AI

Purpose: improve the existing script without leaving the screen.

V1 can be simple:

- button opens a small inline instruction input
- example placeholder: `Make it punchier and keep it under 45 seconds`
- calls DeepSeek with existing script and instruction

This can be deferred if implementation needs to stay small, but the UI should reserve the location.

## Scene Tags

The script editor should support optional text conventions:

```text
[Scene] Cats are secretly efficient hunters.
[Visual] close-up cat watching moving light
[Text] Tiny hunter mode
```

Parser behavior for first implementation:

- `[Scene]` starts a scene beat
- `[Visual]` maps to `visual_brief`
- `[Text]` maps to `on_screen_text`
- plain text without tags uses natural sentence parsing

If tags are not implemented immediately, they should remain documented as a target and not be shown as a broken promise.

## Parse Scenes

When user clicks `Parse scenes` or `Use current script`:

1. Save script to project.
2. Apply current split settings.
3. Generate `ScenePlan` records.
4. Navigate to Scene Plan flow.

Current backend can support this with:

```text
PATCH /api/videodesign/projects/{project_id}/scenes/{scene_id}
POST /api/videodesign/projects/{project_id}/plan
```

Needed improvement:

```text
PATCH /api/videodesign/projects/{project_id}
```

or reuse an endpoint to update project script before planning.

## Split Controls On This Screen

Do not expose technical split controls as the main decision.

Use copy:

```text
Scene pacing
Dense     fast cuts
Normal    balanced
Sparse    slower narration
Manual    use line breaks
```

Advanced row:

```text
Max words per scene
```

Definition:

- only a safety limit for overlong sentences
- not a fixed scene size

## Loading States

DeepSeek generation:

- disable script actions
- status: `Generating script...`
- show progress row in activity log
- allow cancel only as UI placeholder unless backend cancellation exists

Parse scenes:

- status: `Parsing scenes...`
- should complete quickly
- on success, navigate to plan

## Error States

`DEEPSEEK_API_KEY_MISSING`:

- message: `DeepSeek API key is missing. Add DEEPSEEK_API_KEY in .env or use current script.`
- keep script textarea editable

`SCRIPT_GENERATION_FAILED`:

- message: `Script generation failed. You can retry or continue with your own script.`

Empty script:

- message: `Add an idea or script before continuing.`

Invalid DeepSeek JSON:

- fallback: attempt to extract script text if available
- if no usable content, show typed error

## Data State

Project fields touched:

```json
{
  "idea": "",
  "script_source": "deepseek|user|deepseek_pending",
  "script": "",
  "target_duration_seconds": 45,
  "split_settings": {},
  "scenes": []
}
```

When script changes after scene planning:

- mark scenes as stale or require re-plan
- V1 can show `Script changed - re-plan scenes`

## Acceptance Criteria

- User can generate a script from idea using DeepSeek.
- User can paste/edit a script and continue without DeepSeek.
- User can see word count, duration estimate, and expected scene count.
- User can choose scene pacing in plain language.
- `max_words_per_scene` is visibly secondary/advanced.
- User cannot accidentally start Douyin search from this screen.
- Script edits persist to `project.json`.
- Generated scenes are inspectable on the next screen before material search.

## Implementation Notes

Keep this flow independent from template and material search.

The important implementation boundary:

```text
Script Creation outputs a clean project script and optional initial scene hints.
It does not choose final videos.
```

