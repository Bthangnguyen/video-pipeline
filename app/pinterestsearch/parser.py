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


def parse_api_payloads(
    payloads: list[dict],
    limit: int,
    media_type: PinterestMediaFilter = "video",
    aspect_ratio: PinterestAspectFilter = "9:16",
    tolerance: float = 0.18,
) -> list[PinterestResult]:
    results: list[PinterestResult] = []
    seen: set[str] = set()
    for payload in payloads:
        for pin in _pins_from_payload(payload):
            result = _result_from_pin(pin)
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
                return results
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


def _pins_from_payload(payload: dict) -> list[dict]:
    data = (payload.get("resource_response") or {}).get("data") or {}
    results = data.get("results") if isinstance(data, dict) else None
    if not isinstance(results, list):
        return []
    return [item for item in results if isinstance(item, dict)]


def _result_from_pin(pin: dict) -> PinterestResult:
    pin_id = str(pin.get("id") or "")
    video = _best_video(pin)
    image = _best_image(pin)
    pinner = pin.get("pinner") or {}
    media_url = str(video.get("url") or image.get("url") or "")
    cover_url = str(video.get("thumbnail") or image.get("url") or media_url)
    width = _int(video.get("width") or image.get("width"))
    height = _int(video.get("height") or image.get("height"))
    title = str(pin.get("grid_title") or pin.get("title") or pin.get("description") or "").strip()
    return PinterestResult(
        result_id=f"pinr_{uuid.uuid4().hex}",
        pin_id=pin_id,
        title=title,
        description=str(pin.get("description") or "").strip(),
        media_type="video" if video else "image",
        media_remote_url=media_url,
        cover_remote_url=cover_url,
        width=width,
        height=height,
        aspect_ratio=aspect_label(width, height),
        source_url=f"https://www.pinterest.com/pin/{pin_id}/" if pin_id else "",
        author_name=str(pinner.get("full_name") or pinner.get("username") or "").strip(),
        author_url=f"https://www.pinterest.com/{pinner.get('username')}/" if pinner.get("username") else "",
        raw=pin,
    )


def _best_video(pin: dict) -> dict:
    video_list = ((pin.get("videos") or {}).get("video_list") or {})
    if not isinstance(video_list, dict):
        return {}
    videos = [item for item in video_list.values() if isinstance(item, dict) and item.get("url")]
    if not videos:
        return {}
    mp4_videos = [item for item in videos if ".mp4" in str(item.get("url", "")).lower()]
    candidates = mp4_videos or videos
    return max(candidates, key=lambda item: _int(item.get("width")) * _int(item.get("height")))


def _best_image(pin: dict) -> dict:
    images = pin.get("images") or {}
    if not isinstance(images, dict):
        return {}
    for key in ("orig", "736x", "564x", "474x", "236x", "170x"):
        image = images.get(key)
        if isinstance(image, dict) and image.get("url"):
            return image
    valid_images = [item for item in images.values() if isinstance(item, dict) and item.get("url")]
    if not valid_images:
        return {}
    return max(valid_images, key=lambda item: _int(item.get("width")) * _int(item.get("height")))


def _pin_id_from_url(url: str) -> str:
    match = re.search(r"/pin/(\d+)", urlparse(url).path)
    return match.group(1) if match else ""


def _int(value) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0
