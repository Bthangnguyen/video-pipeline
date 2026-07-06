import os
from dataclasses import dataclass
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


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


_load_env_file()


@dataclass(frozen=True)
class Settings:
    cookie_file: Path = Path(os.getenv("DOUYIN_COOKIE_FILE", "./secrets/douyin-cookies.json"))
    browser_headless: bool = _bool_env("DOUYIN_BROWSER_HEADLESS", True)
    browser_profile_dir: Path = Path(os.getenv("DOUYIN_BROWSER_PROFILE_DIR", "./storage/browser/douyin"))
    use_direct_api: bool = _bool_env("DOUYIN_USE_DIRECT_API", False)
    signature_dir: Path = Path(
        os.getenv(
            "DOUYIN_SIGNATURE_DIR",
            "./vendor/Douyin_TikTok_Download_API/crawlers/douyin/web",
        )
    )
    result_ttl_seconds: int = int(os.getenv("DOUYIN_RESULT_TTL_SECONDS", "1800"))
    debug: bool = _bool_env("DOUYIN_DEBUG", False)


settings = Settings()
