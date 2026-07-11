# 12 Shared Search Pools And Popular-First Search Flow

Status: planned V3. This flow replaces per-scene keyword generation from the earlier V3 draft while keeping the source-specific lessons implemented in V2.

## Goal

Make material search simpler, faster, and easier to control:

- search a small number of broad keywords instead of one keyword per scene;
- let many scenes share one result pool;
- reserve exact searches for visible subjects that truly need to be shown;
- optionally request popular Douyin results first;
- keep every generated group and keyword editable before search.

The core shift is:

```text
Old: scene -> generate keyword -> search
New: project -> generate shared search groups -> assign scenes -> search each unique group once
```

There is no search profile, theme catalog, or channel-level prompt system.

## Product Principle

Most narration does not need literal footage.

A Japan video can use broad searches such as `Japan` or `Japan life` for several scenes. The opening can use one related attention query such as `Japanese woman` or `Japanese students`. Only a named location, product, object, or demonstrable behavior creates another exact search.

The planner should minimize the number of searches while preserving the few subjects that viewers must recognize.

## Search Group Roles

### `base`

The default group for general narration.

Use it for:

- abstract explanations;
- statistics and claims;
- cultural commentary;
- emotions, causes, and outcomes;
- connective narration;
- scenes that only need a relevant visual world.

Keyword behavior:

- use one broad topic or context phrase;
- prefer a phrase people commonly browse;
- do not describe the sentence;
- do not add camera, quality, aspect-ratio, or editing words.

Examples:

| Project context | Douyin | Pinterest |
| --- | --- | --- |
| Japan culture | `日本生活` | `Japan life` |
| Cats | `猫咪日常` | `cats` |
| Technology | `科技生活` | `technology` |
| Street food | `街头美食` | `street food` |

Every project must have exactly one `base` group.

### `hook`

An optional shared group for the first attention beat, normally scene 1 or the first 1-3 seconds.

Use it when a broader but still topic-related subject is more visually attractive than the base group.

Keyword behavior:

- keep the project context;
- use a high-supply, visually attractive subject or environment;
- remain simple and platform-native;
- never invent an unrelated story merely to obtain attractive footage.

Examples:

| Project context | Douyin | Pinterest |
| --- | --- | --- |
| Japan lifestyle | `日本女生` | `Japanese woman` |
| Japan school culture | `日本学生` | `Japanese students` |
| Cats | `可爱猫咪` | `cute cat` |
| Food | `美食制作` | `cooking close up` |

The `hook` group may be merged into `base` when the base query is already strong enough.

### `exact`

Create an exact group only when a viewer needs to recognize a visible subject mentioned by the narration.

Valid triggers:

- named city, landmark, or place;
- named product, model, tool, or device;
- specific food or ingredient central to the explanation;
- visible technique, mechanism, or behavior whose demonstration is evidence;
- any concrete object whose identity matters to the claim.

Keyword behavior:

- search the entity name first;
- add one common observable action only when the entity name alone is ambiguous;
- do not turn the full narration into a query;
- reuse the same exact group across every scene discussing that entity.

Examples:

| Narration subject | Douyin | Pinterest |
| --- | --- | --- |
| Tokyo | `东京` | `Tokyo` |
| Cooling head pad | `降温帽垫` | `cooling head pad` |
| Neck cooling ring | `冰凉圈` | `neck cooling ring` |
| Cat slow blink demonstration | `猫咪 慢眨眼` | `cat slow blink` |

The presence of a noun alone does not require an exact group.

## Grouping Decision

The planner evaluates all scenes in one request.

For each scene:

1. Use `hook` only for the opening attention beat.
2. Ask whether a concrete subject must be recognized to understand or trust the line.
3. If yes, assign an existing or new `exact` group.
4. Otherwise assign `base`.
5. Deduplicate groups with the same subject before returning.

Compact rule:

```text
Opening attention beat                         -> hook
Concrete + necessary to recognize or prove    -> exact
Everything else                               -> base
```

Examples:

| Narration | Assignment |
| --- | --- |
| Why Japanese adults miss school life | `hook` for the opening, otherwise `base` |
| School dominated their teenage years | `base` |
| Adult life becomes stressful | `base` |
| Tokyo summers are getting hotter | `exact:tokyo` |
| First, cooling head pads | `exact:cooling_head_pad` |
| This makes summer easier | `base` |

## Keyword Contract

Each source receives one simple primary keyword per group.

Douyin:

- simplified Chinese;
- normally 1-3 concepts;
- common creator or viewer search language;
- no Japanese kana;
- no `4K`, `vertical`, `cinematic`, `viral`, or sentence-style explanation.

Pinterest:

- simple English;
- normally 1-4 concepts;
- no `vertical`, `cinematic`, `aesthetic`, `4K`, or detailed shot direction;
- media type and aspect ratio remain application filters.

The planner must not append `video` or `raw footage` by default. These words may be used only when platform testing proves the plain subject query returns the wrong media category.

Each group has at most one internal fallback. The fallback must be broader than the primary query.

## Proposed Data Contract

Project search plan:

```json
{
  "popular_first": true,
  "groups": [
    {
      "group_id": "grp_hook",
      "role": "hook",
      "label": "Opening hook",
      "douyin_keyword": "日本女生",
      "pinterest_keyword": "Japanese woman",
      "douyin_fallback": "日本生活",
      "pinterest_fallback": "Japan life",
      "scene_ids": ["scn_001"]
    },
    {
      "group_id": "grp_base",
      "role": "base",
      "label": "Japan life",
      "douyin_keyword": "日本生活",
      "pinterest_keyword": "Japan life",
      "douyin_fallback": "日本",
      "pinterest_fallback": "Japan",
      "scene_ids": ["scn_002", "scn_003", "scn_006"]
    },
    {
      "group_id": "grp_tokyo",
      "role": "exact",
      "label": "Tokyo",
      "exact_subject": "Tokyo",
      "douyin_keyword": "东京",
      "pinterest_keyword": "Tokyo",
      "douyin_fallback": "日本城市",
      "pinterest_fallback": "Japan city",
      "scene_ids": ["scn_004", "scn_005"]
    }
  ]
}
```

Scene reference:

```json
{
  "scene_id": "scn_004",
  "search_group_id": "grp_tokyo"
}
```

Candidate additions:

```json
{
  "search_group_id": "grp_tokyo",
  "source_rank": 1,
  "stats": {
    "digg_count": 0,
    "comment_count": 0,
    "share_count": 0,
    "collect_count": 0,
    "play_count": 0
  },
  "popularity": {
    "requested": true,
    "applied": true,
    "method": "douyin_most_liked",
    "publish_window_days": 180
  }
}
```

Candidates belong to a search group. Scenes reference the group and can approve different candidates from the same pool.

## Search Execution

1. Generate the complete group plan from the full script.
2. Show groups and scene assignments before any search starts.
3. Let the user edit keywords, merge groups, or move a scene to another group.
4. Read the `Popular first` toggle.
5. Build one task per unique tuple:

```text
(source, normalized keyword, popular_first, media_type, aspect_ratio)
```

6. Search each tuple once.
7. Persist partial results after every completed source task.
8. Expose the shared candidate pool to every assigned scene.
9. Mark a candidate already selected by another scene, while still allowing deliberate reuse.
10. Preserve all results and approvals if another group fails.

A ten-scene video with one hook, one base group, and two exact subjects performs four unique keyword searches per source, not ten.

## Popular-First Mode

### UX Contract

Materials contains one visible toggle:

```text
Popular first  [on/off]
```

Recommended default: on for new searches.

The setting applies to the current search batch and is persisted on the project. Turning it off restores platform relevance ordering for the next search. Existing candidate order is not silently changed; the group must be searched again.

The UI must call this mode `Popular first`, not `Trending`, because V1 does not calculate engagement velocity or global trend rank.

### Douyin Behavior

The official Douyin video-search contract exposes:

- `sort_type=0`: composite relevance;
- `sort_type=1`: most liked;
- `sort_type=2`: newest;
- `publish_time=0|1|7|180`: unrestricted, one day, seven days, or 180 days.

Official reference:

`https://developer.open-douyin.com/docs/resource/zh-CN/dop/develop/openapi/douyin-search-capability/aweme-dy-video-search`

V1 mapping:

| Toggle | Douyin sort | Publish window |
| --- | --- | --- |
| Off | Composite relevance | Unrestricted |
| On | Most liked | 180 days |

For direct API search, send the corresponding request parameters.

For Playwright search:

- open the Douyin result filter;
- select `最多点赞`;
- select the 180-day publish window when the UI exposes it;
- record which filters were actually applied;
- do not fail the search when the filter UI changes.

Ordering fallback:

1. Preserve platform order when the requested filter was applied.
2. If the filter could not be applied and every candidate has a parsed like count, use a stable descending `digg_count` sort.
3. If statistics are incomplete, preserve platform order and report `popular_unavailable`.

No custom viral score is calculated.

### Pinterest Behavior

The current Pinterest browser-search path does not provide a reliable public popularity sort or complete engagement metrics for arbitrary search results.

Pinterest's official analytics APIs expose engagement metrics for known or account-related Pins, while its Trends API identifies trending keywords rather than reordering arbitrary public search results. Those capabilities are not equivalent to a public `most popular videos for this keyword` filter.

Official references:

- `https://developers.pinterest.com/docs/analytics-and-reports/organic-reporting/`
- `https://developers.pinterest.com/docs/analytics-and-reports/trends/`

V1 therefore:

- keeps Pinterest's returned order;
- shows `Platform order` beside Pinterest results;
- never fabricates a popularity rank;
- may support Pinterest popularity later only when a reliable metric is available for every candidate.

## Materials UI

### Search Plan View

Before search, show compact group rows:

```text
[Hook]  Japanese woman            1 scene
[Base]  Japan life                5 scenes
[Exact] Tokyo                     2 scenes
[Exact] Cooling head pad          2 scenes
```

Each row supports:

- edit Douyin keyword;
- edit Pinterest keyword;
- view assigned scenes;
- move a scene to another group;
- merge compatible groups;
- search or re-search only that group.

Do not show a separate keyword form for every scene.

### Search Controls

Global controls:

- `Popular first` toggle;
- source toggles for Douyin and Pinterest;
- aspect-ratio filter;
- candidate count;
- `Search all groups` button.

Group status examples:

- `Searching Douyin: 日本生活`;
- `12 Douyin candidates, popular sort applied`;
- `8 Pinterest candidates, platform order`;
- `Popular sort unavailable; using Douyin result order`.

### Candidate Review

- display candidates by group;
- allow scene-by-scene approval from the shared pool;
- show which scene already uses a candidate;
- keep inline preview;
- show Douyin like count when available;
- show a clear `Popular` or `Platform order` badge;
- never display a made-up quality or viral score.

## Fallback Rules

- A failed `hook` search falls back to the `base` pool.
- A failed `exact` search may show the `base` pool as a labeled fallback.
- An exact group never silently changes its keyword or assignment.
- One group failure never removes successful groups or their candidates.
- Retry only the failed source and group.
- Persist each completed result batch immediately.

## Implementation Phases

### Phase 1: Search Plan And Grouping

- [ ] Add a project-level search plan containing shared groups.
- [ ] Generate one `base`, zero or one `hook`, and only necessary `exact` groups.
- [ ] Assign every scene to exactly one group.
- [ ] Deduplicate repeated exact subjects.
- [ ] Preserve user-edited groups and assignments unless regeneration is explicit.

### Phase 2: Group-Based Search

- [ ] Execute each normalized source keyword once.
- [ ] Store candidates by `search_group_id`.
- [ ] Share a candidate pool across assigned scenes.
- [ ] Prevent accidental duplicate selection while allowing explicit reuse.
- [ ] Persist partial group results independently.

### Phase 3: Popular-First Douyin Search

- [ ] Add `popular_first` to Material search requests and project state.
- [ ] Map the toggle to official Douyin sort and publish-time parameters.
- [ ] Apply equivalent filters through Playwright when available.
- [ ] Parse and persist Douyin statistics.
- [ ] Add diagnostics for requested, applied, and unavailable sorting.

### Phase 4: Materials UI

- [ ] Replace per-scene keyword forms with group rows.
- [ ] Add group editing and scene reassignment.
- [ ] Add the global `Popular first` toggle.
- [ ] Show source-specific ordering badges and statistics.
- [ ] Keep inline preview and current approval behavior.

### Phase 5: Tests

- [ ] Verify ten general scenes can share one base search.
- [ ] Verify the opening can use one separate hook group.
- [ ] Verify repeated mentions of Tokyo share one exact group.
- [ ] Verify named products create exact groups while abstract nouns do not.
- [ ] Verify keyword edits update every assigned scene.
- [ ] Verify each unique tuple searches once.
- [ ] Verify Popular first maps to Douyin most-liked plus 180 days.
- [ ] Verify turning the toggle off restores composite relevance.
- [ ] Verify missing Douyin filter controls do not fail search.
- [ ] Verify Pinterest remains explicitly labeled as platform order.
- [ ] Verify partial results survive another group failure.

## Non-Goals

- No search profiles or theme selectors.
- No keyword per scene by default.
- No vision-model quality score.
- No subjective beauty, cleanliness, copyright, or hook score.
- No claim that most-liked results are globally trending.
- No Pinterest popularity rank without complete, reliable metrics.
- No automatic overwrite of user-edited groups.

## Acceptance Criteria

- A project uses one search per unique group and source, not one search per scene.
- General scenes reuse a broad base pool.
- The opening may use a separate simple hook pool.
- Named locations and products use shared exact pools only when visually necessary.
- Generated keywords remain short and platform-native.
- Users can edit groups and scene assignments before search.
- Users can turn Popular first on or off.
- Douyin reports whether most-liked ordering was actually applied.
- Pinterest clearly reports platform ordering instead of fake popularity.
- Every scene can approve a distinct candidate from its shared pool.
- Partial results and prior approvals survive individual search failures.
