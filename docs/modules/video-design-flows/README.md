# Video Design Flow Specs

Status: draft for UI/UX implementation.

This folder splits the VideoDesign product into focused functional flows based on the reference screenshots in `design template/`.

## Flow Map

```text
Project Start
-> Script Creation
-> Template & Preset Setup
-> Scene Plan & Material Review
-> Studio Timeline
-> Trim Selection & Render Assembly
-> Studio Creative Controls
-> Studio Continuity & Render
-> Studio Transition, Caption Drag & Playhead
-> Studio Audio, BGM & Event-Driven SFX
-> Platform-Native Visual Search
-> Shared Search Pools & Popular-First Search
```

Each flow should feel like a dedicated screen, not a section in one long form.

## Specs

- [01 Project Start Flow](01-project-start-flow.md)
- [02 Script Creation Flow](02-script-creation-flow.md)
- [03 Template Preset Flow](03-template-preset-flow.md)
- [04 Scene Plan And Material Review Flow](04-scene-plan-material-review-flow.md)
- [05 Studio Timeline Flow](05-studio-timeline-flow.md)
- [06 Trim Selection And Render Assembly Flow](06-trim-render-flow.md)
- [07 Studio Creative Controls Flow](07-studio-creative-controls-flow.md)
- [08 Studio Continuity And Render Flow](08-studio-continuity-render-flow.md)
- [09 Studio Transition, Caption Drag, And Playhead Flow](09-studio-transition-caption-playhead-flow.md)
- [10 Studio Audio, BGM, And Event-Driven SFX Flow](10-studio-audio-bgm-sfx-flow.md)
- [11 Platform-Native Visual Search Flow](11-platform-native-visual-search-flow.md)
- [12 Shared Search Pools And Popular-First Search Flow](12-shared-search-pools-popular-first-flow.md)

## Shared Shell

All post-login/project screens use the same shell:

- left global icon rail
- top project/action bar when inside a project
- main working canvas
- optional sticky right summary rail
- light setup pages, studio workspace with stronger editing controls

Global icon rail:

```text
Home
Projects
Douyin Search
Templates
Studio
Settings
```

Project action bar:

```text
Project title | Save state | Undo | Redo | Preview | Export disabled until render module exists
```

## UX Rules

- Show one primary decision per screen.
- Keep generated/expensive actions behind explicit CTA buttons.
- Persist after every meaningful change.
- Make the current project state visible without requiring the user to inspect JSON.
- Do not start Douyin search until script, scene plan, and preset choices are visible.
- Studio must work from downloaded `MaterialAsset` files, not expiring Douyin result IDs.
