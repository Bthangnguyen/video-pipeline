import json
import os
import re

import httpx

from app.videodesign.config import settings
from app.videodesign.errors import DEEPSEEK_API_KEY_MISSING, SCRIPT_GENERATION_FAILED, VideoDesignError


VISUAL_SEARCH_SYSTEM_PROMPT = """You are a search-query planner for raw short-form video footage on Douyin and Pinterest.

Your output is used directly in each platform's search box. Optimize in this exact order:
1. Grounded in the actual project and scene.
2. Broad enough to return many useful videos.
3. Likely to return real-life, minimally edited footage.
4. Visually clear and useful to a short-form editor.

Return JSON only. Do not wrap it in markdown.

Grounding rules:
- First identify the project's persistent subject. Then plan all scenes together.
- For each scene, choose a concrete content_anchor from the project idea, full script, or nearby scene context. Write it in English using 1-3 words.
- If a scene is a sentence fragment, inherit the subject from the surrounding scenes. Never interpret the fragment alone.
- A visual proxy is allowed only when it is a common, direct depiction of the script idea and still contains the project or scene anchor.
- Never invent a couple, attractive person, doctor, office worker, country, room, object, or activity that is not supported by the input.
- A country, demographic, or broad word such as family is context, not permission to invent a different story.

Breadth rules:
- The primary query is a high-recall category query, not a detailed shot description.
- Prefer one concrete subject plus one observable action or object. Add at most one necessary context modifier.
- Remove facts, percentages, explanations, causes, conclusions, moods, camera directions, lighting, and decorative adjectives.
- Do not add vertical, cinematic, aesthetic, 4k, viral, trending, shocking, or similar style words. The application already filters media type and aspect ratio.
- Do not use an exact voiceover sentence or a niche factual claim.
- Fallbacks must change the visual route, not make the primary query longer or more specific.

Raw-footage rules:
- Favor ordinary observable actions: walking, cooking, working, shopping, entering a home, playing, reacting, using an object, or a real environment.
- For Douyin, use simplified Chinese creator language with 2-4 short terms. Always write Chinese for Douyin even when the footage is about Japan, Korea, or another country. Never output Japanese kana or Japanese spellings. For example, use 玄关, 实拍, 孩子, 袜子, and 榻榻米, not 玄関, 実写, 子供, 靴下, or 畳. 实拍, 日常, or 随手拍 may be used only when the query remains broad.
- For Pinterest, use 2-6 simple English words. "video" or "raw footage" may be appended, but the content phrase must remain broad.
- Avoid terms that attract text-heavy or edited results: explainer, facts, tips, meaning, tutorial, podcast, news, interview, compilation, edit, meme, quote, lyrics, slideshow, 科普, 解说, 盘点, 合集, 教程, 文案, 语录, 混剪, 剪辑.

Hook rule:
- Scene 1 may use a stronger visual proxy, but it must still preserve the true project anchor. Relevance is more important than a generic beauty or reaction hook.

Granularity examples only; never copy their topic into another project:
- Street shoes carry bacteria -> 玄关 脱鞋 日常 / taking shoes off at home video
- A cat's slow blink signals trust -> 猫咪 慢眨眼 / cat slow blink video
- AI saves office time -> 上班族 电脑办公 / office worker using laptop video
- Grocery prices rose -> 超市 买菜 实拍 / grocery shopping video
- Romance disappeared, in a relationship project -> 情侣 冷战 日常 / couple sitting apart video

Critical counterexample:
- If the project is about Japanese home customs, shoes, tatami, or hygiene, never output couple conflict, dating, or bedroom footage merely because "Japan" or "family" appears.

Before returning, silently reject and rewrite any scene where:
- content_anchor is absent from the project or script context;
- the query introduces a new story or unsupported person;
- the query has more than one subject, one action, and one context modifier;
- the likely results are explainers, edits, caption-heavy posts, or an overly narrow staged shot.

Return exactly this JSON shape:
{
  "project_anchor": "",
  "global_hook_strategy": {
    "domain": "",
    "hook_type": "",
    "why_it_hooks": "",
    "douyin_primary_keyword": "",
    "pinterest_primary_keyword": "",
    "fallbacks": {"douyin": [], "pinterest": []}
  },
  "scenes": [
    {
      "scene_id": "",
      "retention_role": "hook|setup|evidence|escalation|twist|payoff|bridge",
      "content_anchor": "",
      "visible_action": "",
      "visual_intent": "",
      "visual_archetype": "",
      "douyin_primary_keyword": "",
      "pinterest_primary_keyword": "",
      "fallbacks": {"douyin": [], "pinterest": []},
      "avoid": [],
      "material_notes": ""
    }
  ]
}"""


class DeepSeekScriptClient:
    endpoint = "https://api.deepseek.com/chat/completions"

    async def generate(self, idea: str, target_duration_seconds: float, tone: str, language: str) -> dict:
        api_key = os.getenv("DEEPSEEK_API_KEY", settings.deepseek_api_key)
        if not api_key:
            raise VideoDesignError(DEEPSEEK_API_KEY_MISSING, "DEEPSEEK_API_KEY is required to generate scripts.")

        target_words = max(30, int(float(target_duration_seconds or 45) * 2.45))
        scene_count = max(3, min(24, round(float(target_duration_seconds or 45) / 4.5)))
        prompt = (
            "Write a short-form video script as JSON only. "
            "Return keys: title, hook, script, scenes. "
            "Each scene must include voiceover_text, on_screen_text, visual_brief, search_keywords. "
            f"Language: {language}. Target duration seconds: {target_duration_seconds}. "
            f"Keep the total voiceover around {target_words} words, within 15 percent. "
            f"Use about {scene_count} scenes with natural sentence breaks. "
            "Do not write a much longer generic script. "
            f"Tone: {tone}. Idea: {idea}"
        )
        try:
            async with httpx.AsyncClient(timeout=45.0) as client:
                response = await client.post(
                    self.endpoint,
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json={
                        "model": os.getenv("DEEPSEEK_MODEL", settings.deepseek_model),
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.7,
                    },
                )
                response.raise_for_status()
                content = response.json()["choices"][0]["message"]["content"]
                return _parse_json_object(content)
        except VideoDesignError:
            raise
        except Exception as exc:
            raise VideoDesignError(SCRIPT_GENERATION_FAILED, f"DeepSeek script generation failed: {exc}", retryable=True) from exc

    async def generate_search_keywords(
        self,
        voiceover_text: str,
        visual_brief: str,
        on_screen_text: str,
        language: str,
    ) -> list[str]:
        api_key = os.getenv("DEEPSEEK_API_KEY", settings.deepseek_api_key)
        if not api_key:
            raise VideoDesignError(DEEPSEEK_API_KEY_MISSING, "DEEPSEEK_API_KEY is required for smart search keywords.")

        prompt = (
            "Return JSON only with key search_keywords as a list containing exactly 1 stock-video search query. "
            "Choose the single broadest visual query that is likely to return raw footage, b-roll, or clean original video. "
            "Prefer concrete visible subjects/actions/places over exact voiceover fragments. "
            "The query should be 2 to 5 words, simple, searchable, and not too niche. "
            "Avoid captions, quotes, emotions without visual subject, abstract phrases, and words like 'not', 'it's', or sentence fragments. "
            "Good pattern: '<subject> <action/location> raw footage' only when raw footage fits naturally. "
            f"Language: {language}. "
            f"Voiceover: {voiceover_text}. "
            f"On-screen text: {on_screen_text}. "
            f"Visual brief: {visual_brief}."
        )
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    self.endpoint,
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json={
                        "model": os.getenv("DEEPSEEK_MODEL", settings.deepseek_model),
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.25,
                    },
                )
                response.raise_for_status()
                content = response.json()["choices"][0]["message"]["content"]
                data = _parse_json_object(content)
        except VideoDesignError:
            raise
        except Exception as exc:
            raise VideoDesignError(SCRIPT_GENERATION_FAILED, f"DeepSeek keyword generation failed: {exc}", retryable=True) from exc
        keywords = [str(item).strip() for item in data.get("search_keywords", []) if str(item).strip()]
        return keywords[:1]

    async def generate_visual_search_keywords(
        self,
        *,
        project_idea: str,
        full_script: str,
        scenes: list[dict],
        language: str,
        target_style: str = "mixed",
    ) -> dict:
        api_key = os.getenv("DEEPSEEK_API_KEY", settings.deepseek_api_key)
        if not api_key:
            raise VideoDesignError(DEEPSEEK_API_KEY_MISSING, "DEEPSEEK_API_KEY is required for smart search keywords.")

        payload = {
            "video_idea": project_idea,
            "full_script": full_script,
            "language": language,
            "target_style": target_style,
            "scenes": scenes,
        }
        try:
            async with httpx.AsyncClient(timeout=35.0) as client:
                response = await client.post(
                    self.endpoint,
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json={
                        "model": os.getenv("DEEPSEEK_MODEL", settings.deepseek_model),
                        "messages": [
                            {"role": "system", "content": VISUAL_SEARCH_SYSTEM_PROMPT},
                            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                        ],
                        "temperature": 0.15,
                    },
                )
                response.raise_for_status()
                content = response.json()["choices"][0]["message"]["content"]
                return _parse_json_object(content)
        except VideoDesignError:
            raise
        except Exception as exc:
            raise VideoDesignError(SCRIPT_GENERATION_FAILED, f"DeepSeek visual search keyword generation failed: {exc}", retryable=True) from exc


def _parse_json_object(content: str) -> dict:
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, flags=re.S)
        if not match:
            raise VideoDesignError(SCRIPT_GENERATION_FAILED, "DeepSeek did not return a JSON object.")
        return json.loads(match.group(0))
