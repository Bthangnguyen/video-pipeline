# 11 Platform-Native Visual Search Flow

Status: draft.

## Goal

Improve material search by making the model think like a short-form editor searching Douyin/TikTok/Pinterest, not like a text summarizer extracting script keywords.

This flow solves two product problems:

1. Find more hookable footage on Douyin and Pinterest.
2. Replace the current keyword prompt with a visual-search prompt that works across many topics, not only relationship or attractive-person hooks.

## Core Principle

Good search keywords are not literal script summaries.

They are platform-native visual queries:

- Douyin queries should look like terms a Chinese creator or viewer would type.
- Pinterest queries should look like visual/stock/aesthetic search terms.
- The first hook query may intentionally be less literal than the script if it creates a stronger first-frame reason to watch.

Example:

```text
Bad literal query:
Japanese married couples do not have intimacy

Better Douyin query:
情侣 冷战
夫妻 分房睡
婚后生活

Better Pinterest query:
asian couple bedroom awkward silence video
couple backs turned in bed vertical video
```

## What Made The Reference Hook Work

The YouTube reference did not hook mainly because it found exact footage for the claim. It hooked because the first seconds combined:

- taboo relationship topic
- attractive human subject
- big captions
- red arrow
- countdown/number framing
- fast visual switching
- bedroom/couple tension later in the sequence

The product should learn this structure, not blindly repeat "pretty girl" for every topic.

## Search Strategy

### 1. Separate Hook Search From Scene Search

Each project gets a `hook_visual_query` for the first 1-3 seconds. It is optimized for attention and topical relevance.

Each scene gets `scene_visual_query` for narrative support.

Hook footage can be broader than the scene:

- relationship topic: face/reaction/couple tension
- money topic: cash/luxury/proof/shocked reaction
- health topic: doctor/body warning/hospital/scan
- crime topic: CCTV/police tape/interview/dark street
- AI/tech topic: screen/hacker/robot/futuristic UI
- productivity topic: stressed desk/phone addiction/before-after
- food topic: close-up cooking/eating reaction/kitchen action
- travel topic: destination street/walking POV/local crowd
- history topic: archival photo/map/crowd/old footage style

### 2. Generate Platform-Specific Keywords

Do not generate one universal keyword and translate it mechanically.

For each scene:

- `douyin_primary_keyword`: simplified Chinese, 2-6 short terms, creator/search language.
- `pinterest_primary_keyword`: English, visual/stock/aesthetic language, usually includes `video` or `vertical video`.
- `fallback_keywords`: internal retries, not all shown in UI by default.

### 3. Use Creator-Language Categories

Douyin examples:

| Domain | Useful Douyin query families |
| --- | --- |
| Relationship | `情侣 冷战`, `夫妻 日常`, `婚后生活`, `夫妻 分房睡`, `情侣 吵架` |
| Parenthood | `宝妈 带娃`, `爸爸带娃`, `一家三口 日常`, `带娃 崩溃` |
| Money | `赚钱 日常`, `老板 生活`, `奢侈品 街拍`, `年轻人 买房`, `现金 展示` |
| Health | `医生 科普`, `医院 日常`, `体检`, `焦虑`, `睡眠 问题` |
| Crime/mystery | `监控 画面`, `真实事件`, `反转`, `采访`, `警方 通报` |
| AI/tech | `人工智能`, `机器人`, `程序员 日常`, `黑客`, `科技感` |
| Productivity | `学习 自律`, `上班族 崩溃`, `手机 成瘾`, `熬夜 工作` |
| Beauty/fashion | `街拍`, `穿搭`, `妆容`, `日系 女生`, `反应` |
| Food | `做饭 日常`, `美食 制作`, `厨房`, `吃播`, `街头 小吃` |
| Travel | `城市 街拍`, `旅行 日常`, `东京 街头`, `夜景`, `人流` |

Pinterest examples:

| Domain | Useful Pinterest query families |
| --- | --- |
| Relationship | `couple awkward silence vertical video`, `couple backs turned in bed video` |
| Parenthood | `tired mom kitchen vertical video`, `parents with kids at home video` |
| Money | `luxury lifestyle money aesthetic video`, `cash counting close up vertical video` |
| Health | `doctor consultation vertical video`, `hospital hallway cinematic video` |
| Crime/mystery | `cctv footage dark street`, `police tape cinematic vertical video` |
| AI/tech | `futuristic computer screen video`, `programmer desk night vertical video` |
| Productivity | `stressed office worker vertical video`, `phone addiction close up video` |
| Food | `cooking close up vertical video`, `street food preparation video` |
| Travel | `tokyo street night vertical video`, `city walking pov vertical video` |

### 4. Avoid Bad Keywords

The generator must avoid:

- exact voiceover sentences
- abstract claims with no visual subject
- single function words or sentence fragments
- statistics as search terms
- niche factual statements
- moral conclusions
- generic "viral video" or "trending" with no subject
- overusing attractive-person hooks for unrelated topics

Bad examples:

```text
22 percent wives intimacy effort
romance disappeared
it is not
last one is insane
normal or sad
people do not care anymore
```

Better examples:

```text
夫妻 分房睡
woman washing dishes tired video
doctor warning patient consultation video
cash counting close up video
监控 画面 反转
```

## Output Schema

The new model output should be one visual search plan:

```json
{
  "global_hook_strategy": {
    "domain": "relationship",
    "hook_type": "taboo relationship tension",
    "why_it_hooks": "Uses a human face and couple tension to make the taboo claim feel immediate.",
    "douyin_primary_keyword": "日系 女生 街拍",
    "pinterest_primary_keyword": "asian woman reaction close up vertical video",
    "fallbacks": {
      "douyin": ["情侣 冷战", "婚后生活"],
      "pinterest": ["couple awkward silence bedroom video"]
    }
  },
  "scenes": [
    {
      "scene_id": "scn_001",
      "retention_role": "hook",
      "visual_intent": "taboo relationship tension with an attention-grabbing human subject",
      "visual_archetype": "human reaction / couple tension",
      "douyin_primary_keyword": "情侣 冷战",
      "pinterest_primary_keyword": "couple awkward silence bedroom video",
      "fallbacks": {
        "douyin": ["婚后生活", "夫妻 日常"],
        "pinterest": ["married couple tension vertical video"]
      },
      "avoid": ["news", "podcast", "anime", "slideshow", "text heavy"],
      "material_notes": "Prefer human face, vertical frame, minimal text overlay."
    }
  ]
}
```

## System Prompt Draft

Use this as the replacement direction for `DeepSeekScriptClient.generate_search_keywords` or a new `generate_visual_search_plan` method.

Standalone prompt file: [`../prompts/visual-search-director-system-prompt.md`](../prompts/visual-search-director-system-prompt.md).

```text
You are a short-form video visual search director.

Your job is not to summarize the script. Your job is to choose search keywords that a human editor would type into Douyin/TikTok/Pinterest to find hookable vertical footage.

Return JSON only.

Rules:
- Convert abstract script ideas into concrete visible situations.
- Think in platform-native search language.
- For Douyin, write simplified Chinese keywords that match creator/viewer search behavior. Use short phrases like 情侣 冷战, 夫妻 日常, 宝妈 带娃, 街拍, 监控 画面.
- For Pinterest, write English visual/aesthetic/stock-style queries. Include "video" or "vertical video" when useful.
- Do not translate word-for-word. Rewrite the query for what the footage should visually show.
- Do not output exact voiceover sentences, statistics, moral judgments, or sentence fragments.
- Do not overuse attractive women or beauty hooks. Use that only when the topic is relationship, dating, social life, beauty, fashion, lifestyle, or the script visually benefits from a human reaction. For other domains choose a domain-fit hook.
- Prefer raw footage, creator skits, real-life scenes, POV footage, close-ups, faces, action, and clear visual situations.
- Avoid podcast clips, news screenshots, anime, slideshows, lyrics, heavy captions, and unrelated memes unless the scene explicitly needs a meme/explainer style.
- Each scene must have exactly one primary Douyin keyword and one primary Pinterest keyword.
- Fallbacks may contain up to 2 keywords per source.
- Keep primary keywords concise: Douyin 2-6 Chinese terms; Pinterest 3-8 English words.

Input:
- video idea
- full script
- scene id/order
- voiceover text
- on-screen text
- visual brief if present
- target source platforms: douyin, pinterest
- target style: raw footage / skit / aesthetic / meme / mixed

Output JSON:
{
  "global_hook_strategy": {
    "domain": "",
    "hook_type": "",
    "why_it_hooks": "",
    "douyin_primary_keyword": "",
    "pinterest_primary_keyword": "",
    "fallbacks": {
      "douyin": [],
      "pinterest": []
    }
  },
  "scenes": [
    {
      "scene_id": "",
      "retention_role": "hook|setup|evidence|escalation|twist|payoff|bridge",
      "visual_intent": "",
      "visual_archetype": "",
      "douyin_primary_keyword": "",
      "pinterest_primary_keyword": "",
      "fallbacks": {
        "douyin": [],
        "pinterest": []
      },
      "avoid": [],
      "material_notes": ""
    }
  ]
}
```

## UI Behavior

Materials should show:

- one editable `Douyin keyword` chip/input
- one editable `Pinterest keyword` chip/input
- optional collapsed fallback list
- source-specific search buttons
- `Search both sources` action

Do not show a long comma-separated keyword list by default. The user should mainly approve or edit one strong keyword per source.

## Backend Behavior

Recommended implementation:

1. Add a new visual-search plan generator.
2. Store source-specific keywords on each scene or in a sidecar `visual_search_plan`.
3. Douyin search uses `douyin_primary_keyword` directly and disables generic Google Translate for LLM-generated Chinese keywords.
4. Pinterest search uses `pinterest_primary_keyword` and preserves the existing media-type/aspect filters.
5. If primary search fails, retry fallbacks internally.
6. Store `search_keyword` on every candidate as today.
7. Keep no quality score. Let the user preview and approve.

## Example: Japanese Marriage Script

```json
{
  "global_hook_strategy": {
    "domain": "relationship",
    "hook_type": "taboo relationship curiosity",
    "why_it_hooks": "The subject is intimate and surprising, so the first visual should be a face or couple-tension image that feels immediately personal.",
    "douyin_primary_keyword": "日系 女生 街拍",
    "pinterest_primary_keyword": "asian woman reaction close up vertical video",
    "fallbacks": {
      "douyin": ["情侣 冷战", "婚后生活"],
      "pinterest": ["couple awkward silence bedroom video"]
    }
  },
  "scenes": [
    {
      "scene_id": "scn_hook",
      "retention_role": "hook",
      "visual_intent": "attention-grabbing relationship taboo",
      "visual_archetype": "human reaction / attractive adult face / relationship tension",
      "douyin_primary_keyword": "日本女生 街拍",
      "pinterest_primary_keyword": "asian woman reaction close up vertical video",
      "fallbacks": {
        "douyin": ["日系 美女 反应", "情侣 冷战"],
        "pinterest": ["asian couple relationship tension vertical video"]
      },
      "avoid": ["minor", "anime", "news", "podcast", "slideshow"],
      "material_notes": "Use only adult-looking subjects. The visual supports the hook but does not need to literally show married couples."
    },
    {
      "scene_id": "scn_effort",
      "retention_role": "evidence",
      "visual_intent": "intimacy feels like a chore",
      "visual_archetype": "tired partner / household chore",
      "douyin_primary_keyword": "女生 做家务 累",
      "pinterest_primary_keyword": "woman washing dishes tired video",
      "fallbacks": {
        "douyin": ["家庭主妇 洗碗", "婚后 女人"],
        "pinterest": ["tired wife kitchen vertical video"]
      },
      "avoid": ["podcast", "quote", "text heavy"],
      "material_notes": "Prefer visible action over abstract emotion."
    },
    {
      "scene_id": "scn_kids",
      "retention_role": "escalation",
      "visual_intent": "relationship turns into household management after kids",
      "visual_archetype": "parents with kids at home",
      "douyin_primary_keyword": "夫妻 带娃 日常",
      "pinterest_primary_keyword": "parents with kids at home video",
      "fallbacks": {
        "douyin": ["宝妈 带娃", "一家三口 日常"],
        "pinterest": ["tired parents home routine vertical video"]
      },
      "avoid": ["news", "cartoon", "slideshow"],
      "material_notes": "Use family routine, home mess, or child interruption."
    }
  ]
}
```

## Acceptance Criteria

- The keyword generator can produce different hook strategies for at least relationship, money, health, crime, AI/tech, productivity, food, and travel topics.
- Douyin keywords are Chinese platform-native phrases, not literal translations.
- Pinterest keywords are English visual queries, not exact script sentences.
- Materials UI can show one editable primary keyword per source.
- Search can retry fallbacks without exposing a noisy keyword list.
- The first scene can use hook footage that is topical but not literal.
- The system avoids using attractive-person hooks as a universal default.
