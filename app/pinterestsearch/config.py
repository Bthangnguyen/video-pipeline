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
class PinterestSettings:
    cookie_file: Path = Path(
        os.getenv("PINTEREST_COOKIE_FILE", r"D:\Workspaces\automation videos\pinterest.txt")
    )
    browser_headless: bool = _bool_env("PINTEREST_BROWSER_HEADLESS", True)
    browser_profile_dir: Path = Path(os.getenv("PINTEREST_BROWSER_PROFILE_DIR", "./storage/browser/pinterest"))
    download_dir: Path = Path(os.getenv("PINTEREST_DOWNLOAD_DIR", "./storage/pinterestsearch/downloads"))
    result_ttl_seconds: int = int(os.getenv("PINTEREST_RESULT_TTL_SECONDS", "1800"))
    debug: bool = _bool_env("PINTEREST_DEBUG", False)


settings = PinterestSettings()
