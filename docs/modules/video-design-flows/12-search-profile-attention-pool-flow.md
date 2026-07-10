# 12 Search Profile, Attention Pool, And Popularity Flow

Status: planned V3. This spec follows the implemented broad-grounded V2 flow in `11-platform-native-visual-search-flow.md`.

## Goal

Make material search optimize for footage people want to keep watching, while switching to exact footage only when the narration names a concrete product or object that must be shown.

The primary product decision is:

```text
Default scene -> attention_pool
Concrete product/object scene -> exact_subject
```

Search behavior is driven by a reusable visual search profile. The script topic supplies context and a minimum relevance boundary; it does not force every scene into a literal query.

## Research Basis

Reference Shorts:

- `https://www.youtube.com/shorts/JdpY1_un6xQ`
- `https://www.youtube.com/shorts/w5p_5pcwbwM`

Local research files:

- `storage/research/youtube_reference_shorts/JdpY1_un6xQ/source.mp4`
- `storage/research/youtube_reference_shorts/w5p_5pcwbwM/source.mp4`

Observed shared pattern:

- both videos default to attractive people, appealing places, lifestyle footage, recognizable faces, movement, and already popular creator footage;
- abstract narration continues using this attention footage instead of searching the literal sentence;
- only concrete cooling products in the second video override the default and use exact demonstrations;
- after the concrete explanation, the edit returns to attractive or contextual footage;
- captions, arrows, crop, and fast cuts amplify the footage but do not replace the need for a strong source clip.

## Core Model

### Search Profile

A search profile is a persistent visual direction for a channel, series, or project.

Example:

```json
{
  "profile_id": "japan_visual",
  "context_terms": ["Japan", "Japanese"],
  "attention_driver": "attractive people and appealing Japanese lifestyle",
  "attention_queries": {
    "douyin": ["日本美女 日常", "日本女生 街拍", "日本生活", "日本风景"],
    "pinterest": ["Japanese woman lifestyle", "Japanese street style", "beautiful Japan"]
  },
  "popularity_policy": {
    "sort": "most_liked",
    "publish_window_days": 180
  }
}
```

The selected profile stays stable across multiple videos so footage style is predictable and testable.

### Scene Modes

`attention_pool`:

- default for abstract explanations, statistics, cultural context, emotion, transitions, and general narration;
- uses one of the profile's broad high-supply queries;
- prioritizes popularity and visual appeal over literal sentence matching;
- must retain the profile context, but does not need to reproduce the sentence.

`exact_subject`:

- used for a named product, tool, food, landmark, device, animal breed, exercise, or other concrete subject that viewers need to recognize;
- searches the concrete subject and, when useful, its demonstration or use;
- prioritizes relevance before popularity;
- falls back to `attention_pool` when exact results are missing or visibly poor.

### Mode Decision

```text
Can the viewer understand the narration without seeing this exact object?

Yes -> attention_pool
No  -> exact_subject
```

Examples:

| Narration | Mode | Query direction |
| --- | --- | --- |
| Why Japanese adults miss school life | `attention_pool` | Japanese youth, attractive lifestyle, school culture |
| Life becomes stressful after graduation | `attention_pool` | Japanese work life, salaryman, city crowds |
| Cooling head pad | `exact_subject` | Cooling head pad demonstration |
| Ice ring | `exact_subject` | Neck cooling ring demonstration |
| This makes summer easier | `attention_pool` | Attractive Japanese summer lifestyle |

## Douyin Popularity Capability

Douyin video search supports these official sort modes:

- `0`: composite relevance;
- `1`: most liked;
- `2`: newest.

It also supports publish windows such as one day, seven days, and 180 days.

Official reference:

`https://developer.open-douyin.com/docs/resource/zh-CN/dop/develop/openapi/douyin-search-capability/aweme-dy-video-search`

V1 policy:

```json
{
  "attention_pool": {
    "sort": "most_liked",
    "publish_window_days": 180
  },
  "exact_subject": {
    "sort": "relevance",
    "publish_window_days": 0
  }
}
```

This is an objective popularity policy, not a subjective quality score.

### Current Gaps

The current repository already parses Douyin `statistics`, but:

- browser search does not select `most liked` or a publish-time filter;
- results are accepted in the order returned by Douyin;
- `MediaCandidate` does not persist source statistics;
- DOM fallback extracts cards without structured popularity data;
- the working direct API path is optional and may be blocked by anti-bot checks;
- no project-level search profile or scene search mode exists yet.

## Generalized Profiles

The two-mode engine is shared. Only the attention pool changes.

| Profile family | Attention pool | Typical exact subject |
| --- | --- | --- |
| Human lifestyle | Attractive adults, fashion, reactions, daily life | Clothing, beauty product, named location |
| Animals | Cute or surprising pet behavior | Breed, toy, pet product, named behavior |
| Family | Cute children, warm family activity | Child product, school item, household object |
| Home | Beautiful interiors, transformations, satisfying routines | Furniture, appliance, cleaning tool |
| Food | Texture, cooking motion, street food, reactions | Dish, ingredient, cooking device |
| Travel | Beautiful people, streets, landscapes, local lifestyle | Landmark, vehicle, hotel, attraction |
| Money and luxury | Cars, cash, homes, shopping, status | App, card, device, named product |
| Fitness | Attractive athletic adults, body movement, transformation | Exercise, machine, wearable |
| Technology | Robots, gadgets, machines, futuristic environments | Named device, software, product demo |
| Mystery and danger | Unusual events, tension, CCTV-like action | Incident, place, tool, evidence object |

Profile prompts are injected separately. The base system prompt must not contain every profile's examples.

## Proposed Data Contract

Project-level fields:

```json
{
  "visual_search_profile": {
    "profile_id": "japan_visual",
    "context_terms": ["Japan"],
    "attention_queries": {
      "douyin": [],
      "pinterest": []
    },
    "popularity_policy": {}
  }
}
```

Scene-level fields:

```json
{
  "visual_search_plan": {
    "mode": "attention_pool|exact_subject",
    "pool_id": "japan_attractive_lifestyle",
    "exact_subject": "",
    "douyin_primary_keyword": "",
    "pinterest_primary_keyword": "",
    "sort": "most_liked|relevance|newest",
    "publish_window_days": 180,
    "reason": ""
  }
}
```

Candidate fields to preserve:

```json
{
  "stats": {
    "digg_count": 0,
    "comment_count": 0,
    "share_count": 0,
    "collect_count": 0,
    "play_count": 0
  },
  "source_rank": 0,
  "search_mode": "attention_pool"
}
```

## Implementation Tasks

### Phase 1: Data And Douyin Sorting

- [ ] Add `sort` and `publish_window_days` to Douyin search requests.
- [ ] Add `stats`, `source_rank`, and `search_mode` to `MediaCandidate`.
- [ ] Preserve available Douyin statistics from parser through Material review and Redis/project JSON.
- [ ] Add deterministic helpers for missing or mixed numeric stat values.
- [ ] Keep original Douyin ordering when structured stats are unavailable.

### Phase 2: Playwright Search Filters

- [ ] In browser search, open Douyin's filter control after results load.
- [ ] Select `最多点赞` for `attention_pool`.
- [ ] Select the requested publish-time window when available.
- [ ] Keep composite relevance for `exact_subject`.
- [ ] Capture and report which filter was actually applied in diagnostics.
- [ ] Do not fail the search when the filter UI changes; fall back to composite ordering.

### Phase 3: Search Profile Planner

- [ ] Store one selected search profile on the project.
- [ ] Generate or select the project attention pool once, not once per scene.
- [ ] Classify each scene only as `attention_pool` or `exact_subject`.
- [ ] Generate exact keywords only for concrete-subject scenes.
- [ ] Rotate attention queries to avoid obvious duplicate footage.
- [ ] Return to the attention pool immediately after an exact-subject beat.
- [ ] Keep source-specific Douyin and Pinterest queries editable in Materials.

### Phase 4: Materials UI

- [ ] Add a project search-profile selector before keyword generation.
- [ ] Show the scene mode and assigned content pool.
- [ ] Allow switching a scene between `attention_pool` and `exact_subject`.
- [ ] Show Douyin like/comment/share counts when available.
- [ ] Add `Most liked`, `Recent popular`, and `Relevance` search policies.
- [ ] Keep inline preview and manual approval as the final decision.

### Phase 5: Cross-Profile Prototype Tests

- [ ] Create one fixture project for each of the ten profile families.
- [ ] Test an abstract scene, a concrete product scene, and a fallback scene per profile.
- [ ] Verify attention scenes never generate literal sentence queries.
- [ ] Verify concrete products use exact-subject search.
- [ ] Verify popularity filters do not break browser fallback search.
- [ ] Record candidate count, no-result rate, and user approval rate per query.
- [ ] Do not introduce subjective candidate scoring without a vision model.

## Search Execution

Recommended V1 execution:

1. Generate or load the project search profile.
2. Classify scene mode.
3. For `attention_pool`, search a broad profile query using `most_liked` and a 180-day window.
4. For `exact_subject`, search the product/object using composite relevance.
5. Request a wider result pool before taking the final candidate count.
6. Persist source order and all available popularity metadata.
7. Show results for user approval.
8. If exact results are empty or unusable, retry with the attention pool.

Initial limits:

- retrieve up to 20 Douyin results per query;
- display 6 candidates per scene;
- use one primary query and one internal fallback;
- do not calculate a custom viral score in V1.

## Limitations

- `most liked` means popular within the keyword result set, not globally trending on Douyin;
- all-time likes favor older viral videos, so recent popularity needs a publish window;
- arbitrary public search results may not expose reliable play count;
- high engagement does not guarantee clean footage, little text, or reuse rights;
- Pinterest does not expose the same structured popularity controls, so its result order and user review remain more important;
- visual attractiveness between two candidates still requires user review or a future vision model.

## Acceptance Criteria

- Abstract Japan culture scenes use the configured attention pool instead of literal queries.
- Named cooling products use exact demonstration queries.
- The scene after a product explanation can return to the attention pool.
- Douyin attention searches apply `most liked` when the UI/API supports it.
- Douyin stats survive into Material review and persisted project state.
- Search remains functional when stats or filter UI are unavailable.
- The same engine runs across all ten profile families without adding their examples to the base prompt.
- User-edited queries and scene modes are never overwritten unless regeneration is explicitly requested.
