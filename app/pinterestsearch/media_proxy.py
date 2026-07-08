from pathlib import Path

import httpx
from fastapi.responses import Response

from app.pinterestsearch.cookies import cookie_header_from_file
from app.pinterestsearch.errors import NETWORK_ERROR, PinterestSearchError
from app.pinterestsearch.schemas import PinterestResult


class MediaProxy:
    def __init__(self, cookie_file: Path):
        self.cookie_file = cookie_file

    async def proxy_media(self, result: PinterestResult, range_header: str | None = None):
        return await self._proxy_url(result.media_remote_url or result.cover_remote_url, range_header)

    async def proxy_cover(self, result: PinterestResult):
        return await self._proxy_url(result.cover_remote_url or result.media_remote_url)

    async def _proxy_url(self, url: str, range_header: str | None = None):
        if not url:
            raise PinterestSearchError(NETWORK_ERROR, "Pinterest media URL is missing.", retryable=True)
        headers = {
            "user-agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "referer": "https://www.pinterest.com/",
        }
        if self.cookie_file.exists():
            cookie_header = cookie_header_from_file(self.cookie_file)
            if cookie_header:
                headers["cookie"] = cookie_header
        if range_header:
            headers["range"] = range_header
        try:
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                passthrough_headers = {}
                for key in ("content-range", "accept-ranges", "content-length"):
                    if key in response.headers:
                        passthrough_headers[key] = response.headers[key]
                return Response(
                    content=response.content,
                    status_code=response.status_code,
                    media_type=response.headers.get("content-type", "application/octet-stream"),
                    headers=passthrough_headers,
                )
        except httpx.HTTPError as exc:
            raise PinterestSearchError(NETWORK_ERROR, f"Pinterest media proxy failed: {exc}", retryable=True) from exc
