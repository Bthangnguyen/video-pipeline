import os
from pathlib import Path


def _load_env_file(path: Path = Path(".env")) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip().lstrip("\ufeff"), value.strip().strip('"').strip("'"))


_load_env_file()


class VideoDesignSettings:
    deepseek_api_key: str = os.getenv("DEEPSEEK_API_KEY", "")
    deepseek_model: str = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
    default_language: str = os.getenv("VIDEODESIGN_DEFAULT_LANGUAGE", "en")
    tts_provider: str = os.getenv("VIDEODESIGN_TTS_PROVIDER", "free_tts")
    tts_voice_id: str = os.getenv("VIDEODESIGN_TTS_VOICE_ID", "en-US-AriaNeural")
    storage_dir: Path = Path(os.getenv("VIDEODESIGN_STORAGE_DIR", "./storage/videodesign")).resolve()


settings = VideoDesignSettings()
