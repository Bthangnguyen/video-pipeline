import json
import os
import re

import httpx

from app.videodesign.config import settings
from app.videodesign.errors import DEEPSEEK_API_KEY_MISSING, SCRIPT_GENERATION_FAILED, VideoDesignError


class DeepSeekScriptClient:
    endpoint = "https://api.deepseek.com/chat/completions"

    async def generate(self, idea: str, target_duration_seconds: float, tone: str, language: str) -> dict:
        api_key = os.getenv("DEEPSEEK_API_KEY", settings.deepseek_api_key)
        if not api_key:
            raise VideoDesignError(DEEPSEEK_API_KEY_MISSING, "DEEPSEEK_API_KEY is required to generate scripts.")

        prompt = (
            "Write a short-form video script as JSON only. "
            "Return keys: title, hook, script, scenes. "
            "Each scene must include voiceover_text, on_screen_text, visual_brief, search_keywords. "
            f"Language: {language}. Target duration seconds: {target_duration_seconds}. Tone: {tone}. Idea: {idea}"
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
            "Return JSON only with key search_keywords as a list of 2 or 3 short stock-video search queries. "
            "Choose broad visual keywords, not exact voiceover fragments. "
            "Prefer raw footage that is likely clean, vertical, natural, and has little or no embedded text. "
            "Avoid niche abstract phrases, captions, quotes, and words like 'not', 'it's', or sentence fragments. "
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
        return keywords[:3]


def _parse_json_object(content: str) -> dict:
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, flags=re.S)
        if not match:
            raise VideoDesignError(SCRIPT_GENERATION_FAILED, "DeepSeek did not return a JSON object.")
        return json.loads(match.group(0))
