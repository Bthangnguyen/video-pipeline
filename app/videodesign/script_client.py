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


def _parse_json_object(content: str) -> dict:
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, flags=re.S)
        if not match:
            raise VideoDesignError(SCRIPT_GENERATION_FAILED, "DeepSeek did not return a JSON object.")
        return json.loads(match.group(0))
