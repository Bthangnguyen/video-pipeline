import re
import uuid
from typing import Any

from app.douyinsearch.schemas import DouyinResult


def parse_search_payload(payload: dict[str, Any], limit: int) -> list[DouyinResult]:
    items = payload.get("data") or payload.get("aweme_list") or payload.get("items") or []
    results: list[DouyinResult] = []
    if not isinstance(items, list):
        return results

    for item in items:
        aweme = _extract_aweme(item)
        if not aweme:
            continue
        result = parse_aweme(aweme)
        if result and result.douyin_aweme_id:
            results.append(result)
        if len(results) >= limit:
            break
    return results


def parse_aweme(aweme: dict[str, Any]) -> DouyinResult | None:
    aweme_id = str(aweme.get("aweme_id") or aweme.get("awemeId") or aweme.get("id") or "")
    if not aweme_id:
        return None

    video = aweme.get("video") if isinstance(aweme.get("video"), dict) else {}
    author = aweme.get("author") if isinstance(aweme.get("author"), dict) else {}
    description = aweme.get("desc") or aweme.get("description") or aweme.get("title") or ""
    stats = aweme.get("statistics") if isinstance(aweme.get("statistics"), dict) else {}

    return DouyinResult(
        result_id=f"dyr_{uuid.uuid4().hex}",
        douyin_aweme_id=aweme_id,
        title=description,
        description=description,
        author_name=author.get("nickname", "") or author.get("name", ""),
        author_id=author.get("sec_uid", "") or author.get("uid", ""),
        cover_remote_url=_first_url(video.get("cover")) or _first_url(video.get("origin_cover")),
        stream_remote_url=_extract_stream_url(video),
        duration=_duration_seconds(video.get("duration")),
        width=int(video.get("width") or 0),
        height=int(video.get("height") or 0),
        stats=stats,
        raw=aweme,
    )


def parse_dom_cards(cards: list[dict[str, Any]], limit: int) -> list[DouyinResult]:
    results: list[DouyinResult] = []
    seen: set[str] = set()
    for card in cards:
        href = str(card.get("href") or "")
        match = re.search(r"/video/(\d+)", href)
        if not match:
            continue
        aweme_id = match.group(1)
        if aweme_id in seen:
            continue
        seen.add(aweme_id)
        title = str(card.get("title") or "")
        results.append(
            DouyinResult(
                result_id=f"dyr_{uuid.uuid4().hex}",
                douyin_aweme_id=aweme_id,
                title=title,
                description=title,
                cover_remote_url=str(card.get("cover_url") or ""),
                raw={"href": href, "dom_card": card},
            )
        )
        if len(results) >= limit:
            break
    return results


def _extract_aweme(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    for key in ("aweme_info", "aweme_detail", "aweme"):
        if isinstance(item.get(key), dict):
            return item[key]
    if item.get("type") not in (None, 1):
        return None
    if item.get("aweme_id") or item.get("awemeId"):
        return item
    return None


def _extract_stream_url(video: dict[str, Any]) -> str:
    for key in ("play_addr", "download_addr"):
        url = _first_url(video.get(key))
        if url:
            return url
    if isinstance(video.get("playapi"), str):
        return video["playapi"]
    bitrate_info = video.get("bitrateInfo") or video.get("bit_rate") or []
    if isinstance(bitrate_info, list):
        for bitrate in bitrate_info:
            if not isinstance(bitrate, dict):
                continue
            url = _first_url(bitrate.get("PlayAddr") or bitrate.get("play_addr"))
            if url:
                return url
    return ""


def _first_url(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        urls = value.get("url_list") or value.get("UrlList") or []
        if isinstance(urls, list) and urls:
            return str(urls[0])
    return ""


def _duration_seconds(duration: Any) -> float:
    try:
        value = float(duration or 0)
    except (TypeError, ValueError):
        return 0
    return value / 1000 if value > 1000 else value

