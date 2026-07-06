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

    async def _proxy_url(self, url: str, media_type: str | None, range_header: str | None = None):
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
        return StreamingResponse(body(), status_code=response.status_code, media_type=content_type, headers=response_headers)


def _stream_from_raw(result: DouyinResult) -> str:
    video = result.raw.get("video") if isinstance(result.raw.get("video"), dict) else {}
    play_addr = video.get("play_addr") if isinstance(video.get("play_addr"), dict) else {}
    urls = play_addr.get("url_list") if isinstance(play_addr.get("url_list"), list) else []
    return str(urls[0]) if urls else ""
