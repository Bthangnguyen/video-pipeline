from pathlib import Path
import re
from urllib.parse import quote, urljoin, urlparse

import httpx
from fastapi.responses import Response

from app.pinterestsearch.cookies import cookie_header_from_file
from app.pinterestsearch.errors import NETWORK_ERROR, PinterestSearchError
from app.pinterestsearch.schemas import PinterestResult


class MediaProxy:
    def __init__(self, cookie_file: Path):
        self.cookie_file = cookie_file

    async def proxy_media(self, result: PinterestResult, range_header: str | None = None, url: str | None = None):
        media_url = result.media_remote_url or result.cover_remote_url
        target_url = self._safe_child_url(media_url, url) if url else media_url
        return await self._proxy_url(target_url, range_header, result.result_id)

    async def proxy_cover(self, result: PinterestResult):
        return await self._proxy_url(result.cover_remote_url or result.media_remote_url)

    async def _proxy_url(self, url: str, range_header: str | None = None, result_id: str | None = None):
        if not url:
            raise PinterestSearchError(NETWORK_ERROR, "Pinterest media URL is missing.", retryable=True)
        headers = {
            "user-agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "referer": "https://www.pinterest.com/",
        }
        if self.cookie_file.exists() and self._should_send_cookie(url):
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
                content_type = response.headers.get("content-type", "application/octet-stream")
                if result_id and self._is_hls_playlist(url, content_type):
                    playlist = self._rewrite_hls_playlist(response.text, url, result_id)
                    return Response(
                        content=playlist,
                        status_code=response.status_code,
                        media_type="application/vnd.apple.mpegurl",
                    )
                return Response(
                    content=response.content,
                    status_code=response.status_code,
                    media_type=content_type,
                    headers=passthrough_headers,
                )
        except httpx.HTTPError as exc:
            raise PinterestSearchError(NETWORK_ERROR, f"Pinterest media proxy failed: {exc}", retryable=True) from exc

    def _safe_child_url(self, root_url: str, child_url: str) -> str:
        root = urlparse(root_url)
        child = urlparse(child_url)
        if child.scheme not in {"http", "https"}:
            raise PinterestSearchError(NETWORK_ERROR, "Invalid Pinterest media URL.", retryable=True)
        if child.hostname != root.hostname:
            raise PinterestSearchError(NETWORK_ERROR, "Pinterest media host mismatch.", retryable=True)
        return child_url

    def _is_hls_playlist(self, url: str, content_type: str) -> bool:
        lowered = content_type.lower()
        return urlparse(url).path.endswith(".m3u8") or "mpegurl" in lowered or "application/vnd.apple.mpegurl" in lowered

    def _should_send_cookie(self, url: str) -> bool:
        host = urlparse(url).hostname or ""
        return host == "pinterest.com" or host.endswith(".pinterest.com")

    def _rewrite_hls_playlist(self, playlist: str, base_url: str, result_id: str) -> str:
        lines = []
        for line in playlist.splitlines():
            if line.startswith("#"):
                lines.append(
                    re.sub(
                        r'URI="([^"]+)"',
                        lambda match: f'URI="{self._hls_proxy_url(base_url, match.group(1), result_id)}"',
                        line,
                    )
                )
            elif line.strip():
                lines.append(self._hls_proxy_url(base_url, line.strip(), result_id))
            else:
                lines.append(line)
        return "\n".join(lines) + "\n"

    def _hls_proxy_url(self, base_url: str, child_path: str, result_id: str) -> str:
        absolute_url = urljoin(base_url, child_path)
        return f"/api/pinterest/results/{result_id}/media?url={quote(absolute_url, safe='')}"
