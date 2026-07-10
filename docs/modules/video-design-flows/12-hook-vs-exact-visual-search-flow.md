# 12 Hook Visual And Exact Visual Search Flow

Status: planned V3. This flow follows the implemented broad-grounded V2 flow in `11-platform-native-visual-search-flow.md`.

## Goal

For every scene, decide only one thing before searching:

```text
Should this scene keep showing visually attractive hook footage,
or must it show a concrete subject mentioned by the narration?
```

There is no search-profile system, channel profile, theme prompt selector, or profile catalog in this flow.

The same decision rule must work for every topic.

## Research Basis

Reference Shorts:

- `https://www.youtube.com/shorts/JdpY1_un6xQ`
- `https://www.youtube.com/shorts/w5p_5pcwbwM`

Local research files:

- `storage/research/youtube_reference_shorts/JdpY1_un6xQ/source.mp4`
- `storage/research/youtube_reference_shorts/w5p_5pcwbwM/source.mp4`

Observed shared behavior:

- both videos default to attractive people, appealing places, movement, and already popular creator footage;
- general narration continues using hook footage instead of illustrating every sentence literally;
- only named cooling products switch to exact demonstrations;
- after the concrete product explanation, the edit returns to hook footage;
- captions, arrows, crop, and fast cuts amplify attention but do not make weak source footage good.

## Two Scene Modes

### `hook_visual`

This is the default.

Use it for:

- abstract claims;
- statistics;
- cultural commentary;
- emotions and outcomes;
- comparisons;
- transitions between ideas;
- sentences whose exact action would produce niche or unattractive search results;
- any line where the viewer does not need to see a specific object to understand the narration.

Search behavior:

- use a broad, topic-adjacent query;
- prioritize popular, attractive, visually pleasing, moving footage;
- keep minimum context relevance, such as Japan for a Japan video;
- do not convert the sentence into a literal search description;
- prefer `most_liked` with a recent publish window when Douyin supports it.

Examples:

| Narration | Mode | Search direction |
| --- | --- | --- |
| Why Japanese adults miss school life | `hook_visual` | Japanese youth, school lifestyle, attractive Japan footage |
| School dominated their teenage years | `hook_visual` | Japanese students, school life |
| It was the peak of their youth | `hook_visual` | Youth, festival, friendship, first love |
| Adult life becomes stressful | `hook_visual` | Salaryman, city crowds, attractive Japan context |
| This makes summer easier | `hook_visual` | Japanese summer lifestyle, attractive people, beautiful places |

### `exact_visual`

Use it only when the viewer needs to recognize a concrete subject.

Typical triggers:

- named product;
- tool or device;
- physical object central to the explanation;
- specific food or ingredient;
- landmark or location that must be identified;
- visible exercise or technique;
- mechanism or demonstration whose proof is the interesting part.

Search behavior:

- search the concrete subject by name;
- add `demo`, `use`, or an observable action only when it is a common search pattern;
- prioritize relevance before popularity;
- return to `hook_visual` after the exact beat;
- fall back to hook footage when exact results are missing or visibly poor.

Examples:

| Narration | Mode | Search direction |
| --- | --- | --- |
| First, cooling head pads | `exact_visual` | Cooling head pad demonstration |
| Put the pad inside your hat | `exact_visual` | Cooling pad used inside hat |
| Next, the ice ring | `exact_visual` | Neck cooling ring demonstration |
| Portable cooling spray | `exact_visual` | Cooling spray test |
| The spray feels refreshing | `hook_visual` unless proof is shown | Attractive summer lifestyle or spray reaction |

## Decision Rule

The classifier follows this order:

1. Identify whether the sentence names a concrete visible subject.
2. Ask whether the viewer must see that subject to understand or trust the narration.
3. Ask whether exact footage is likely to be more interesting than the default hook footage.
4. Use `exact_visual` only when all relevant conditions are satisfied.
5. Otherwise use `hook_visual`.

Compact rule:

```text
Concrete + necessary to recognize + visually demonstrable -> exact_visual
Everything else                                      -> hook_visual
```

The classifier must not choose `exact_visual` merely because a noun exists in the sentence.

Bad exact searches:

- `socks walking on wood floor video`;
- `child putting shoes on rack video`;
- `adults remembering school freedom video`;
- `Japanese work pressure for the rest of life`.

These lines should normally continue using hook footage.

## Douyin Popularity Policy

Douyin video search supports these official sort modes:

- `0`: composite relevance;
- `1`: most liked;
- `2`: newest.

It also supports publish windows such as one day, seven days, and 180 days.

Official reference:

`https://developer.open-douyin.com/docs/resource/zh-CN/dop/develop/openapi/douyin-search-capability/aweme-dy-video-search`

Initial policy:

```json
{
  "hook_visual": {
    "sort": "most_liked",
    "publish_window_days": 180
  },
  "exact_visual": {
    "sort": "relevance",
    "publish_window_days": 0
  }
}
```

This uses objective source popularity. It does not introduce subjective video scoring.

### Current Repository Gaps

The current repository parses Douyin `statistics`, but:

- browser search does not select `most liked` or a publish-time filter;
- results are accepted in the order returned by Douyin;
- `MediaCandidate` does not persist source statistics;
- DOM fallback extracts cards without structured popularity data;
- scene plans do not contain `hook_visual` or `exact_visual` mode.

## Proposed Output

The model receives the full script and all scenes, then returns one decision per scene.

```json
{
  "scenes": [
    {
      "scene_id": "scn_001",
      "mode": "hook_visual",
      "concrete_subject": "",
      "douyin_keyword": "日本女生 校园 日常",
      "pinterest_keyword": "Japanese school lifestyle",
      "sort": "most_liked",
      "publish_window_days": 180,
      "reason": "The narration is an abstract cultural explanation."
    },
    {
      "scene_id": "scn_002",
      "mode": "exact_visual",
      "concrete_subject": "cooling head pad",
      "douyin_keyword": "降温帽垫 使用",
      "pinterest_keyword": "cooling head pad demonstration",
      "sort": "relevance",
      "publish_window_days": 0,
      "reason": "The viewer needs to see the named product and how it is used."
    }
  ]
}
```

No profile ID, profile selector, profile family, or channel-level prompt is required.

## Candidate Data

Preserve objective source metadata when available:

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
  "search_mode": "hook_visual"
}
```

Popularity helps order hook candidates. It does not decide whether footage is clean, attractive, or safe to reuse.

## Implementation Tasks

### Phase 1: Scene Mode Classifier

- [ ] Replace the V3 planning output with only `hook_visual` and `exact_visual` decisions.
- [ ] Generate decisions for all scenes in one LLM request.
- [ ] Make `hook_visual` the default when model output is missing or invalid.
- [ ] Detect named products, tools, devices, landmarks, foods, and visible techniques as exact-subject candidates.
- [ ] Require a reason explaining why exact recognition is necessary.
- [ ] Never create or select a search profile.

### Phase 2: Keyword Generation

- [ ] For `hook_visual`, generate a broad topic-adjacent Douyin and Pinterest query.
- [ ] For `exact_visual`, generate one concrete subject query per source.
- [ ] Avoid literal sentence descriptions for hook scenes.
- [ ] Keep only one primary query and one internal fallback.
- [ ] Return to hook queries after an exact-subject scene.
- [ ] Keep all generated keywords editable before search.

### Phase 3: Douyin Sorting And Stats

- [ ] Add `sort` and `publish_window_days` to Douyin search requests.
- [ ] Add `stats`, `source_rank`, and `search_mode` to `MediaCandidate`.
- [ ] Preserve available Douyin statistics through Material review and persisted project state.
- [ ] Apply `most_liked` for hook scenes when supported.
- [ ] Keep composite relevance for exact scenes.
- [ ] Keep original Douyin ordering when structured stats are unavailable.

### Phase 4: Playwright Filters

- [ ] Open Douyin's filter control after search results load.
- [ ] Select `最多点赞` for `hook_visual`.
- [ ] Select the requested publish-time window when available.
- [ ] Capture which filter was actually applied in diagnostics.
- [ ] Fall back to composite search when the filter UI changes or disappears.

### Phase 5: Materials UI

- [ ] Show a two-state mode control on every scene: `Hook visual` or `Exact visual`.
- [ ] Show the concrete subject only for exact scenes.
- [ ] Let the user override the mode before searching.
- [ ] Show source keywords and available Douyin popularity stats.
- [ ] Keep inline preview and manual approval as the final decision.
- [ ] Do not add a search-profile selector.

### Phase 6: Generalized Tests

- [ ] Test abstract and exact scenes across Japan, animals, food, home, technology, fitness, travel, money, relationships, and family topics.
- [ ] Verify abstract scenes remain `hook_visual` regardless of topic.
- [ ] Verify named products and visually necessary demonstrations become `exact_visual`.
- [ ] Verify a noun alone does not force exact mode.
- [ ] Verify exact-search failure falls back to hook footage.
- [ ] Verify popularity filters do not break browser fallback search.
- [ ] Record candidate count, no-result rate, and user approval rate.
- [ ] Do not add subjective candidate scoring without a vision model.

## Search Execution

1. Send the full script and scenes to the mode classifier.
2. Save one mode and one source-specific query per scene.
3. Search hook scenes with a broad query and `most_liked` when supported.
4. Search exact scenes with the concrete subject and composite relevance.
5. Retrieve a wider result pool before displaying final candidates.
6. Persist source order and all available popularity metadata.
7. Let the user preview and approve.
8. Fall back from failed exact search to the hook query.

Initial limits:

- retrieve up to 20 Douyin results per query;
- display 6 candidates per scene;
- use one primary query and one fallback;
- do not calculate a custom viral score in V1.

## Limitations

- `most liked` means popular inside the keyword result set, not globally trending on Douyin;
- all-time likes favor older viral videos, so recent popularity needs a publish window;
- arbitrary public search results may not expose reliable play count;
- high engagement does not guarantee clean footage, little text, visual attractiveness, or reuse rights;
- Pinterest does not expose the same structured popularity controls;
- choosing between two visually similar candidates still requires user review or a future vision model.

## Acceptance Criteria

- Abstract narration defaults to hook footage instead of literal search.
- Named cooling products use exact demonstration queries.
- Scenes after product demonstrations can return to hook footage.
- The classifier works across topics without theme or profile prompts.
- Douyin hook searches apply `most liked` when available.
- Douyin statistics survive into Material review and persisted project state.
- Search remains functional when stats or filter controls are unavailable.
- User-edited modes and keywords are never overwritten unless regeneration is explicitly requested.
