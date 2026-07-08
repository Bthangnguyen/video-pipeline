from collections.abc import AsyncIterator

import httpx
from fastapi.responses import StreamingResponse

from app.douyinsearch.cookies import cookie_header_from_file
from app.douyinsearch.errors import NETWORK_ERROR, STREAM_RESOLVE_FAILED, DouyinSearchError
from app.douyinsearch.schemas import DouyinResult


class StreamProxy:
    def __init__(self, cookie_file):
        self.cookie_file = cookie_file

    async def proxy_cover(self, result: DouyinResult):
        if not result.cover_remote_url:
            raise DouyinSearchError(STREAM_RESOLVE_FAILED, "No cover URL is available for this result.")
        return await self._proxy_url(result.cover_remote_url, media_type=None)

    async def proxy_stream(self, result: DouyinResult, range_header: str | None = None):
        remote_url = result.stream_remote_url or _stream_from_raw(result)
        if not remote_url:
            raise DouyinSearchError(STREAM_RESOLVE_FAILED, "No stream URL is available for this result.", retryable=True)
        return await self._proxy_url(remote_url, media_type="video/mp4", range_header=range_header)

    async def proxy_download(self, result: DouyinResult):
        remote_url = no_watermark_url_from_result(result)
        if not remote_url:
            raise DouyinSearchError(STREAM_RESOLVE_FAILED, "No no-watermark video URL is available for this result.", retryable=True)
        filename = f"douyin_{result.douyin_aweme_id}.mp4"
        return await self._proxy_url(remote_url, media_type="video/mp4", download_filename=filename)

    async def download_to_file(self, result: DouyinResult, output_path):
        remote_url = no_watermark_url_from_result(result)
        if not remote_url:
            raise DouyinSearchError(STREAM_RESOLVE_FAILED, "No no-watermark video URL is available for this result.", retryable=True)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        headers = self._headers()
        timeout = httpx.Timeout(30.0, read=120.0)
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                async with client.stream("GET", remote_url, headers=headers) as response:
                    response.raise_for_status()
                    with output_path.open("wb") as handle:
                        async for chunk in response.aiter_bytes():
                            handle.write(chunk)
        except httpx.HTTPError as exc:
            raise DouyinSearchError(NETWORK_ERROR, f"Could not download remote media: {exc}", retryable=True) from exc
        return output_path

    async def download_url_to_file(self, remote_url: str, output_path):
        if not remote_url:
            raise DouyinSearchError(STREAM_RESOLVE_FAILED, "No remote video URL is available.", retryable=True)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        headers = self._headers()
        timeout = httpx.Timeout(30.0, read=120.0)
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                async with client.stream("GET", remote_url, headers=headers) as response:
                    response.raise_for_status()
                    with output_path.open("wb") as handle:
                        async for chunk in response.aiter_bytes():
                            handle.write(chunk)
        except httpx.HTTPError as exc:
            raise DouyinSearchError(NETWORK_ERROR, f"Could not download remote media: {exc}", retryable=True) from exc
        return output_path

    async def _proxy_url(
        self,
        url: str,
        media_type: str | None,
        range_header: str | None = None,
        download_filename: str | None = None,
    ):
        headers = self._headers()
        timeout = httpx.Timeout(30.0, read=120.0)
        client = httpx.AsyncClient(timeout=timeout, follow_redirects=True)
        try:
            request_headers = dict(headers)
            if range_header:
                request_headers["Range"] = range_header
            request = client.build_request("GET", url, headers=request_headers)
            response = await client.send(request, stream=True)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            await client.aclose()
            raise DouyinSearchError(NETWORK_ERROR, f"Could not fetch remote media: {exc}", retryable=True) from exc

        async def body() -> AsyncIterator[bytes]:
            try:
                async for chunk in response.aiter_bytes():
                    yield chunk
            finally:
                await response.aclose()
                await client.aclose()

        content_type = response.headers.get("content-type") or media_type or "application/octet-stream"
        response_headers = {}
        for key in ("content-length", "accept-ranges", "content-range"):
            if key in response.headers:
                response_headers[key] = response.headers[key]
        if download_filename:
            response_headers["content-disposition"] = f'attachment; filename="{download_filename}"'
        return StreamingResponse(body(), status_code=response.status_code, media_type=content_type, headers=response_headers)

    def _headers(self) -> dict[str, str]:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "*/*",
            "Accept-Encoding": "identity",
            "Referer": "https://www.douyin.com/",
        }
        if self.cookie_file.exists():
            cookie_header = cookie_header_from_file(self.cookie_file)
            if cookie_header:
                headers["Cookie"] = cookie_header

        return headers


def _stream_from_raw(result: DouyinResult) -> str:
    video = result.raw.get("video") if isinstance(result.raw.get("video"), dict) else {}
    play_addr = video.get("play_addr") if isinstance(video.get("play_addr"), dict) else {}
    urls = play_addr.get("url_list") if isinstance(play_addr.get("url_list"), list) else []
    return str(urls[0]) if urls else ""


def no_watermark_url_from_result(result: DouyinResult) -> str:
    video = result.raw.get("video") if isinstance(result.raw.get("video"), dict) else {}
    bitrate_url = _first_bitrate_url(video)
    if bitrate_url:
        return bitrate_url

    play_addr = video.get("play_addr") if isinstance(video.get("play_addr"), dict) else {}
    play_url = _first_url(play_addr)
    if play_url:
        return play_url.replace("playwm", "play")

    uri = str(play_addr.get("uri") or "")
    if uri:
        return f"https://aweme.snssdk.com/aweme/v1/play/?video_id={uri}&ratio=1080p&line=0"

    return result.stream_remote_url.replace("playwm", "play") if result.stream_remote_url else ""


def _first_bitrate_url(video: dict) -> str:
    bitrate_info = video.get("bit_rate") or video.get("bitrateInfo") or []
    if not isinstance(bitrate_info, list):
        return ""
    for bitrate in bitrate_info:
        if not isinstance(bitrate, dict):
            continue
        play_addr = bitrate.get("play_addr") or bitrate.get("PlayAddr")
        url = _first_url(play_addr)
        if url:
            return url
    return ""


def _first_url(value) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        urls = value.get("url_list") or value.get("UrlList") or []
        if isinstance(urls, list) and urls:
            return str(urls[0])
    return ""
