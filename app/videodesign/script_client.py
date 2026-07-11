import json
import os
import re

import httpx

from app.videodesign.config import settings
from app.videodesign.errors import DEEPSEEK_API_KEY_MISSING, SCRIPT_GENERATION_FAILED, VideoDesignError


VISUAL_SEARCH_SYSTEM_PROMPT = """You plan a small set of shared searches for short-form video footage on Douyin and Pinterest.

Return JSON only. Do not wrap it in markdown.

Core objective:
- Several scenes should reuse one broad search result pool.
- Generate exactly one base group for general narration.
- Generate zero or one hook group for the first 1-3 seconds only when it is more visually attractive than the base group.
- Generate an exact group only for a named location, product, object, food, device, or visible behavior that viewers must recognize.
- Repeated mentions of the same exact subject must share one group.
- Assign every supplied scene_id to exactly one group.
- Minimize the number of groups.

Role rules:
- base: abstract explanations, statistics, commentary, causes, outcomes, emotions, and connective narration.
- hook: the opening attention beat. It may use a broader high-supply subject, but it must remain genuinely related to the project.
- exact: a concrete subject must be seen to understand, trust, or identify the narration.
- A noun alone does not justify exact. Do not search a literal sentence or a niche action unless the visible action is the evidence.

Keyword rules:
- Keep keywords extremely simple. Prefer a broad entity or a common browse phrase.
- Douyin: simplified Chinese, normally 1-3 concepts, natural creator/viewer language. Never output Japanese kana.
- Pinterest: simple English, normally 1-4 concepts.
- Do not append video, raw footage, vertical, cinematic, aesthetic, 4k, viral, trending, camera directions, moods, facts, percentages, or explanations.
- Avoid text-heavy categories such as explainer, facts, tips, tutorial, podcast, news, interview, compilation, edit, meme, quote, lyrics, slideshow, 科普, 解说, 盘点, 合集, 教程, 文案, 语录, 混剪, 剪辑.
- Each group may have one broader fallback per source.

Examples of the desired granularity:
- General Japan narration -> 日本生活 / Japan life
- Opening Japan lifestyle hook -> 日本女生 / Japanese woman
- Japan school opening -> 日本学生 / Japanese students
- Named city -> 东京 / Tokyo
- Named product -> 降温帽垫 / cooling head pad
- Demonstrated behavior -> 猫咪 慢眨眼 / cat slow blink

Do not add a search profile, theme, niche catalog, quality score, or per-scene keyword list.

Return exactly this JSON shape:
{
  "project_anchor": "",
  "groups": [
    {
      "role": "hook|base|exact",
      "label": "",
      "exact_subject": "",
      "douyin_keyword": "",
      "pinterest_keyword": "",
      "douyin_fallback": "",
      "pinterest_fallback": "",
      "scene_ids": []
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
                        "temperature": 0.1,
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
