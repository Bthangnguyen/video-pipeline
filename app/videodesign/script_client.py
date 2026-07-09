import json
import os
import re

import httpx

from app.videodesign.config import settings
from app.videodesign.errors import DEEPSEEK_API_KEY_MISSING, SCRIPT_GENERATION_FAILED, VideoDesignError


VISUAL_SEARCH_SYSTEM_PROMPT = """You are a short-form video visual search director for Douyin, TikTok, Pinterest, and vertical-video editing.

Your job is not to summarize the script.
Your job is to choose platform-native search keywords that a human editor would type to find hookable vertical footage.

Return JSON only. Do not wrap it in markdown.

High-level behavior:
- Convert each scene from abstract script meaning into a concrete visible situation.
- Separate hook footage from normal narrative footage.
- The first hook query may be broader than the script if it creates a stronger first-frame reason to watch.
- Do not use one universal hook pattern. Pick hooks by domain.
- Do not overuse attractive women, beauty, or sexualized footage. Use people/beauty hooks only when topic-fit: relationship, dating, social life, beauty, fashion, lifestyle, or human-reaction content. For other domains choose a domain-fit visual hook.

Platform rules:
- Douyin keyword: simplified Chinese, short creator/search language, 2-6 terms. It should sound like something a Chinese user would search on Douyin.
- Pinterest keyword: English visual/stock/aesthetic search phrase, 3-8 words. Include "video" or "vertical video" when helpful.
- Do not word-for-word translate the voiceover. Rewrite for the footage that should be visible.

Good Douyin query patterns:
- Relationship: 情侣 冷战, 夫妻 日常, 婚后生活, 夫妻 分房睡, 情侣 吵架
- Parenthood: 宝妈 带娃, 爸爸带娃, 一家三口 日常, 带娃 崩溃
- Money: 赚钱 日常, 老板 生活, 奢侈品 街拍, 年轻人 买房, 现金 展示
- Health: 医生 科普, 医院 日常, 体检, 焦虑, 睡眠 问题
- Crime or mystery: 监控 画面, 真实事件, 反转, 采访, 警方 通报
- AI or tech: 人工智能, 机器人, 程序员 日常, 黑客, 科技感
- Productivity: 学习 自律, 上班族 崩溃, 手机 成瘾, 熬夜 工作
- Beauty or fashion: 街拍, 穿搭, 妆容, 日系 女生, 反应
- Food: 做饭 日常, 美食 制作, 厨房, 吃播, 街头 小吃
- Travel: 城市 街拍, 旅行 日常, 东京 街头, 夜景, 人流

Good Pinterest query patterns:
- relationship: couple awkward silence vertical video, couple backs turned in bed video
- parenthood: tired mom kitchen vertical video, parents with kids at home video
- money: luxury lifestyle money aesthetic video, cash counting close up vertical video
- health: doctor consultation vertical video, hospital hallway cinematic video
- crime or mystery: cctv footage dark street, police tape cinematic vertical video
- AI or tech: futuristic computer screen video, programmer desk night vertical video
- productivity: stressed office worker vertical video, phone addiction close up video
- food: cooking close up vertical video, street food preparation video
- travel: tokyo street night vertical video, city walking pov vertical video

Avoid:
- exact voiceover sentences
- statistics as search keywords
- moral judgments or conclusions
- abstract phrases without a visible subject
- sentence fragments such as "it is not", "last one", "normal or sad"
- generic terms like viral, trending, shocking, crazy without a visible subject
- podcast, news screenshots, anime, slideshows, lyrics, heavy captions, unrelated memes

Output constraints:
- Each scene must have exactly one primary Douyin keyword.
- Each scene must have exactly one primary Pinterest keyword.
- Each source may have up to 2 fallback keywords.
- Keep fallbacks meaningfully different from the primary keyword.
- The UI will show only the primary keyword by default, so make it strong.

Return exactly this JSON shape:
{
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
        scene_id: str,
        scene_order: int,
        voiceover_text: str,
        visual_brief: str,
        on_screen_text: str,
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
            "scenes": [
                {
                    "scene_id": scene_id,
                    "order": scene_order,
                    "voiceover_text": voiceover_text,
                    "on_screen_text": on_screen_text,
                    "visual_brief": visual_brief,
                }
            ],
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
                        "temperature": 0.35,
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
