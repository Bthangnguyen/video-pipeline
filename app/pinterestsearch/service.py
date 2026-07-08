from app.pinterestsearch.browser_client import BrowserClient
from app.pinterestsearch.config import settings
from app.pinterestsearch.errors import INVALID_KEYWORD, NO_RESULTS, RESULT_EXPIRED, PinterestSearchError
from app.pinterestsearch.media_proxy import MediaProxy
from app.pinterestsearch.result_store import ResultStore
from app.pinterestsearch.schemas import PinterestResult, PublicPinterestResult, SearchRequest, SearchResponse


class PinterestSearchService:
    def __init__(self):
        self.store = ResultStore(settings.result_ttl_seconds)
        self.browser = BrowserClient(settings.cookie_file, settings.browser_headless, settings.debug)
        self.media_proxy = MediaProxy(settings.cookie_file)

    def health(self) -> dict:
        return {
            "success": True,
            "module": "pinterestsearch",
            "browser_ready": True,
            "cookie_file": str(settings.cookie_file),
            "cookie_file_exists": settings.cookie_file.exists(),
        }

    async def check_session(self) -> dict:
        return await self.browser.check_session()

    async def search(self, request: SearchRequest) -> SearchResponse:
        keyword = request.keyword.strip()
        if not keyword:
            raise PinterestSearchError(INVALID_KEYWORD, "Keyword is required.")

        results, diagnostics = await self.browser.search(request)
        if not results:
            raise PinterestSearchError(NO_RESULTS, "No Pinterest results matched the requested filters.", retryable=True)

        stored = self.store.put_many(results[: request.limit])
        return SearchResponse(
            keyword=keyword,
            media_type=request.media_type,
            aspect_ratio=request.aspect_ratio,
            items=[self._public_result(result) for result in stored],
            diagnostics=diagnostics,
        )

    def get_result(self, result_id: str) -> dict:
        result = self._stored_result(result_id)
        return {"success": True, "item": self._public_result(result)}

    async def proxy_media(self, result_id: str, range_header: str | None = None, url: str | None = None):
        return await self.media_proxy.proxy_media(self._stored_result(result_id), range_header, url)

    async def proxy_cover(self, result_id: str):
        return await self.media_proxy.proxy_cover(self._stored_result(result_id))

    async def close(self) -> None:
        await self.browser.close()

    def _stored_result(self, result_id: str) -> PinterestResult:
        result = self.store.get(result_id)
        if not result:
            raise PinterestSearchError(RESULT_EXPIRED, "Result is expired or does not exist.")
        return result

    def _public_result(self, result: PinterestResult) -> PublicPinterestResult:
        return PublicPinterestResult(
            result_id=result.result_id,
            pin_id=result.pin_id,
            title=result.title,
            description=result.description,
            media_type=result.media_type,
            media_url=f"/api/pinterest/results/{result.result_id}/media",
            cover_url=f"/api/pinterest/results/{result.result_id}/cover",
            width=result.width,
            height=result.height,
            aspect_ratio=result.aspect_ratio,
            source_url=result.source_url,
            author_name=result.author_name,
            author_url=result.author_url,
            diagnostics={
                "has_media": bool(result.media_remote_url),
                "has_cover": bool(result.cover_remote_url),
                "remote_media_type": result.media_type,
            },
        )


pinterest_service = PinterestSearchService()
