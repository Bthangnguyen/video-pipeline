import re
import uuid
from urllib.parse import urlparse

from app.pinterestsearch.schemas import PinterestAspectFilter, PinterestMediaFilter, PinterestResult


ASPECT_TARGETS = {
    "9:16": 9 / 16,
    "1:1": 1.0,
    "16:9": 16 / 9,
}


def parse_dom_cards(
    cards: list[dict],
    limit: int,
    media_type: PinterestMediaFilter = "video",
    aspect_ratio: PinterestAspectFilter = "9:16",
    tolerance: float = 0.18,
) -> list[PinterestResult]:
    results: list[PinterestResult] = []
    seen: set[str] = set()
    for card in cards:
        result = _result_from_card(card)
        if not result.media_remote_url and not result.cover_remote_url:
            continue
        key = result.pin_id or result.media_remote_url or result.cover_remote_url
        if key in seen:
            continue
        seen.add(key)
        if not media_matches(result, media_type, aspect_ratio, tolerance):
            continue
        results.append(result)
        if len(results) >= limit:
            break
    return results


def media_matches(
    result: PinterestResult,
    media_type: PinterestMediaFilter,
    aspect_ratio: PinterestAspectFilter,
    tolerance: float,
) -> bool:
    if media_type != "both" and result.media_type != media_type:
        return False
    if aspect_ratio == "any":
        return True
    if not result.width or not result.height:
        return False
    target = ASPECT_TARGETS[aspect_ratio]
    actual = result.width / result.height
    return abs(actual - target) <= target * tolerance


def aspect_label(width: int, height: int) -> str:
    if not width or not height:
        return ""
    ratio = width / height
    closest = min(ASPECT_TARGETS.items(), key=lambda entry: abs(entry[1] - ratio))
    return closest[0]


def _result_from_card(card: dict) -> PinterestResult:
    href = str(card.get("href") or "")
    pin_id = str(card.get("pin_id") or _pin_id_from_url(href))
    media_type = "video" if card.get("video_url") else "image"
    media_url = str(card.get("video_url") or card.get("image_url") or "")
    cover_url = str(card.get("image_url") or card.get("video_poster") or media_url)
    width = _int(card.get("width"))
    height = _int(card.get("height"))
    return PinterestResult(
        result_id=f"pinr_{uuid.uuid4().hex}",
        pin_id=pin_id,
        title=str(card.get("title") or "").strip(),
        description=str(card.get("description") or "").strip(),
        media_type=media_type,
        media_remote_url=media_url,
        cover_remote_url=cover_url,
        width=width,
        height=height,
        aspect_ratio=aspect_label(width, height),
        source_url=href,
        author_name=str(card.get("author_name") or "").strip(),
        author_url=str(card.get("author_url") or "").strip(),
        raw=card,
    )


def _pin_id_from_url(url: str) -> str:
    match = re.search(r"/pin/(\d+)", urlparse(url).path)
    return match.group(1) if match else ""


def _int(value) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0
