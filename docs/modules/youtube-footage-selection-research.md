# YouTube Shorts Footage Selection Research

Source: `https://www.youtube.com/shorts/cZ6n5KOWgkc`

Local files:

- `storage/research/youtube_cZ6n5KOWgkc/source.mp4`
- `storage/research/youtube_cZ6n5KOWgkc/source.info.json`
- `storage/research/youtube_cZ6n5KOWgkc/contact_sheet_small.jpg`

## Observed Structure

The sample does not select footage by literal script keywords. It uses a fast sequence of emotionally legible, human-first clips:

| Time area | Script role | Footage type | Selection logic |
| --- | --- | --- | --- |
| 0-5s | Hook, country/context, "three reasons" | Asian/Japanese-looking women, nightlife, big arrows/numbers | Grab attention with faces, attractiveness, motion, and visual numbers instead of showing marriage statistics. |
| 6-9s | First reason/intimacy | Couple-in-bedroom skit | Converts an abstract claim into a direct relationship scene. |
| 10-14s | "Mendokusai", effort, chore | Japanese/Asian woman talking, woman washing dishes | Bridges the Japanese word to a familiar chore visual. |
| 15-18s | Kids arrive, husband moved | Bedroom/separate-room skit | Uses a simple domestic setup that instantly reads as separation. |
| 19-21s | Co-managers of household | Parent/child/home scenes | Uses family-management footage, not literal "co-manager" footage. |
| 22-25s | Mama/papa naming | Japanese-language meme/creator clips | Uses culturally specific clips with visible labels and gestures. |
| 26-28s | Romance disappeared | Couple lying apart, muted emotional frame | Ends on a clear emotional proxy: distance/loneliness. |

## Key Finding

This video is built from visual proxies, not exact semantic matches.

Examples:

- "22% of wives say intimacy feels like too much effort" becomes "couple in bedroom" plus "tired woman/chore".
- "They stop being partners and become co-managers" becomes "parents with kids at home".
- "Spouses become mama and papa" becomes "Japanese mama/papa explainer meme".
- "Romance disappeared" becomes "couple lying apart".

The footage is also not clean raw stock. It contains heavy captions, arrows, meme overlays, creator footage, and reaction-style shots. If our product wants safer, cleaner material, we should copy the proxy-selection logic, not the exact source style.

## Main Hook Reason

The first seconds hook because they use short-form attention language:

- attractive human subject
- red arrow
- taboo relationship topic
- bold captions
- numbered countdown
- fast cuts

That does not mean every topic should search for attractive people. It means the search system needs a domain-fit hook layer before normal scene matching.

Examples:

- relationship: human reaction, couple tension, bedroom distance
- money: cash, luxury, proof, shocked reaction
- health: doctor, hospital, body warning, scan
- crime: CCTV, police tape, interview, night street
- AI/tech: computer screen, robot, hacker, futuristic UI
- productivity: stressed desk, phone addiction, before/after routine

For Douyin/TikTok-style search, the query must match platform-native creator language. A user would not search `Japanese married couples do not have intimacy`. They would search terms closer to `情侣 冷战`, `婚后生活`, `夫妻 分房睡`, `日本女生 街拍`, or `宝妈 带娃`.

## Why Simple AI Keywords Fail

Naive keyword extraction would produce phrases like:

- "Japanese married couples"
- "intimacy too much effort"
- "mendokusai"
- "mama papa private"
- "romance disappeared"

Those queries are too niche, abstract, or text-heavy. Search engines will return explainers, memes, unrelated edits, or nothing. The sample works because it maps the script into broad searchable visual situations.

## Recommended Search Strategy

Add a "visual director" step before material search.

For each scene, the LLM should output one approved primary query and optional fallbacks using this reasoning order:

1. Identify the emotional role of the sentence.
2. Convert abstract claims into a concrete visual situation.
3. Prefer broad raw-footage queries with people, place, action, and mood.
4. Avoid over-specific facts unless they are visually necessary.
5. Avoid terms that attract explainers, podcast clips, news, subtitles, anime, or edits.

Suggested per-scene fields:

```json
{
  "scene_id": "scn_...",
  "script_text": "...",
  "emotional_role": "relationship tension",
  "visual_archetype": "couple distant in bedroom",
  "primary_keyword": "asian couple bedroom awkward silence",
  "fallback_keywords": [
    "married couple sitting apart at home",
    "couple backs turned in bed"
  ],
  "avoid_keywords": ["podcast", "news", "anime", "subtitle", "tiktok edit"],
  "shot_type": "close-up or medium shot",
  "material_notes": "Prefer raw domestic footage, faces visible, minimal text overlay."
}
```

## Archetype Library For Relationship Scripts

Useful reusable archetypes:

- `relationship_tension`: couple sitting apart, awkward silence, no eye contact.
- `domestic_fatigue`: tired woman in kitchen, washing dishes, laundry, late-night chores.
- `parenthood_shift`: parents with kids, family morning routine, child interrupting couple.
- `separate_rooms`: person sleeping on sofa, spouse leaving bedroom, separate beds.
- `identity_loss`: parent labels, family role, parent-child routine.
- `lonely_partner`: close-up face, quiet room, window, empty bed side.
- `romance_loss`: couple backs turned in bed, cold dinner, distant walk.
- `cultural_context`: Japanese/Asian apartment, Japanese couple, Tokyo street, family home.

## Query Examples For This Script

| Script idea | Better query |
| --- | --- |
| Japanese married couples do not have intimacy | `asian couple bedroom awkward silence` |
| Three reasons, last one is insane | `japanese women street reaction` |
| Intimacy feels like too much effort | `tired woman at home avoiding partner` |
| Mendokusai means bothersome chore | `japanese woman washing dishes tired` |
| After kids arrive | `parents with child at home exhausted` |
| Husband moved to another room | `husband sleeping separate room` |
| Partners become co-managers | `parents household routine with kids` |
| Spouses call each other mama and papa | `japanese parents mama papa family` |
| Romance disappeared | `couple backs turned in bed lonely` |

## Product Implication

Material search should not ask the LLM to "extract keywords". It should ask the LLM to direct footage:

- What should the viewer see?
- What feeling should the footage create?
- What broad stock-style query is likely to find that visual?
- What should be avoided?

For the UI, show only one primary keyword per scene by default. Keep fallbacks internally for retry when a source returns no results or times out.
