# Broad Grounded Visual Search Prompt

Status: implemented in `app/videodesign/script_client.py` as `VISUAL_SEARCH_SYSTEM_PROMPT`.

## Objective

Generate one source-specific primary query per scene that maximizes useful search recall without drifting away from the script.

Priority order:

1. Grounded in the project and scene.
2. Broad enough to return many candidates.
3. Likely to return ordinary, minimally edited footage.
4. Visually useful for a short-form edit.

Hook strength does not outrank relevance.

## Why V1 Failed

The first prompt contained a large library of domain examples and generated each scene separately. In the `japan family` regression case, a script about genkan, shoes, tatami, and hygiene produced repeated queries such as `Japanese couple sitting apart` and `夫妻 冷战`.

The failure came from three behaviors:

- example anchoring: the model copied relationship archetypes from the prompt;
- isolated planning: a short scene fragment had no neighboring scene context;
- per-source regeneration: Douyin and Pinterest planning could run separately and overwrite the stored plan.

## Required Reasoning Behavior

The model receives all selected scenes in one request and must plan them together.

For every scene it must:

1. Identify a `content_anchor` grounded in the idea, full script, or nearby scene.
2. Convert the scene into one ordinary, observable subject/action.
3. Remove facts, percentages, causes, conclusions, moods, camera directions, and decorative adjectives.
4. Produce a broad category query, not a detailed staged shot.
5. Privately reject the draft if it invents an unsupported person, place, object, or story.

Sentence fragments inherit the persistent subject from surrounding scenes. They are never interpreted alone.

## Query Shape

Douyin:

- simplified Chinese only, including footage about other countries;
- 2-4 short creator-language terms;
- one subject plus one action/object and at most one context modifier;
- optional raw cues: `实拍`, `日常`, `随手拍`;
- avoid terms that attract explainers or edits: `科普`, `解说`, `盘点`, `合集`, `教程`, `文案`, `语录`, `混剪`, `剪辑`.

Pinterest:

- simple English, normally 2-6 words;
- one subject plus one action/object;
- `video` or `raw footage` may be appended;
- do not add `vertical`, `cinematic`, `aesthetic`, `4k`, camera directions, or engagement adjectives.

The application already applies media and aspect-ratio filters, so those constraints do not belong in the content query.

## Granularity Examples

These examples define breadth only and must not be copied into unrelated projects.

| Scene meaning | Douyin | Pinterest |
| --- | --- | --- |
| Street shoes carry bacteria | `玄关 脱鞋 日常` | `taking shoes off at home video` |
| A cat slow blink signals trust | `猫咪 慢眨眼` | `cat slow blink video` |
| AI saves office time | `上班族 电脑办公` | `office worker using laptop video` |
| Grocery prices rose | `超市 买菜 实拍` | `grocery shopping video` |
| Romance disappeared in a relationship script | `情侣 冷战 日常` | `couple sitting apart video` |

Critical regression rule:

```text
Japanese home customs + shoes/tatami/hygiene
must never become
Japanese couple conflict + dating/bedroom footage
```

## Output Contract

```json
{
  "project_anchor": "cat behavior",
  "global_hook_strategy": {
    "domain": "pets",
    "hook_type": "unexpected pet behavior",
    "why_it_hooks": "The action is immediately recognizable.",
    "douyin_primary_keyword": "猫咪 慢眨眼",
    "pinterest_primary_keyword": "cat slow blink video",
    "fallbacks": {"douyin": [], "pinterest": []}
  },
  "scenes": [
    {
      "scene_id": "scn_001",
      "retention_role": "hook",
      "content_anchor": "cat",
      "visible_action": "slow blinking",
      "visual_intent": "show recognizable cat behavior",
      "visual_archetype": "pet behavior",
      "douyin_primary_keyword": "猫咪 慢眨眼",
      "pinterest_primary_keyword": "cat slow blink video",
      "fallbacks": {
        "douyin": ["猫咪 眼神 日常"],
        "pinterest": ["cat face video"]
      },
      "avoid": ["explainer", "compilation", "text heavy"],
      "material_notes": "Prefer one real cat performing the action."
    }
  ]
}
```

## Backend Guardrails

- Match output by exact `scene_id`; never reuse scene 1 output for a missing scene.
- Validate that `content_anchor` occurs in project/script context and remains present in the Pinterest query.
- Reject ungrounded plans and use a local broad fallback.
- Remove Pinterest style/camera modifiers deterministically.
- Normalize common Japanese spellings to simplified Chinese for Douyin; if Japanese kana remains, use the English query and let the Douyin translation path translate it.
- Generate at most once for the selected scene batch. Search uses stored or user-edited keywords unless the user explicitly enables `Regenerate keywords`.

## Acceptance Cases

- `japan family` genkan script contains no couple, dating, sofa, or bedroom query.
- Cat sentence fragments retain `cat` as the content anchor.
- Money, health, AI, food, and travel topics retain their own project anchor instead of copying an unrelated example.
- Primary queries contain no platform filters such as `vertical` and no decorative style stack.
- Douyin queries contain simplified Chinese rather than Japanese spellings.
