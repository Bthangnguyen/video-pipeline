import httpx

from app.douyinsearch.browser_client import BrowserClient
from app.douyinsearch.config import settings
from app.douyinsearch.direct_api_client import DirectApiClient
from app.douyinsearch.errors import (
    DIRECT_API_FAILED,
    INVALID_KEYWORD,
    NO_RESULTS,
    RESULT_EXPIRED,
    DouyinSearchError,
)
from app.douyinsearch.result_store import ResultStore
from app.douyinsearch.schemas import DouyinResult, PublicDouyinResult, SearchRequest, SearchResponse
from app.douyinsearch.stream_proxy import StreamProxy


class DouyinSearchService:
    def __init__(self):
        self.store = ResultStore(settings.result_ttl_seconds)
        self.browser = BrowserClient(
            settings.cookie_file,
            settings.browser_headless,
            settings.debug,
            settings.browser_profile_dir,
        )
        self.direct_api = DirectApiClient()
        self.stream_proxy = StreamProxy(settings.cookie_file)

    def health(self) -> dict:
        return {
            "success": True,
            "module": "douyinsearch",
            "browser_ready": True,
            "cookie_file_exists": settings.cookie_file.exists(),
            "browser_profile_dir": str(settings.browser_profile_dir),
            "browser_profile_exists": settings.browser_profile_dir.exists(),
            "browser_visible_for_login": True,
        }

    async def check_session(self) -> dict:
        return await self.browser.check_session()

    async def preflight_check(self, keyword: str = "cat") -> dict:
        return await self.browser.preflight_check(keyword)

    async def search(self, request: SearchRequest) -> SearchResponse:
        keyword = request.keyword.strip()
        if not keyword:
            raise DouyinSearchError(INVALID_KEYWORD, "Keyword is required.")

        search_keyword = await self._translate(keyword) if request.translate_to_chinese else keyword

        strategy_used = "browser"
        diagnostics = {}
        if request.strategy == "direct_api":
            results, diagnostics = await self.direct_api.search(request, search_keyword)
            strategy_used = "direct_api"
        if request.strategy == "auto" and settings.use_direct_api:
            try:
                results, diagnostics = await self.direct_api.search(request, search_keyword)
                strategy_used = "direct_api"
            except DouyinSearchError as error:
                if error.code != DIRECT_API_FAILED:
                    raise
                diagnostics = {"direct_api_error": error.to_payload()}

        if strategy_used == "browser":
            browser_results, browser_diagnostics = await self._search_browser_with_retries(search_keyword, request.limit)
            results = browser_results
            diagnostics = {**diagnostics, **browser_diagnostics}

        if not results:
            raise DouyinSearchError(NO_RESULTS, "No Douyin results were found.", retryable=True)

        stored = self.store.put_many(results[: request.limit])
        return SearchResponse(
            keyword=keyword,
            search_keyword=search_keyword,
            strategy_used=strategy_used,
            items=[self._public_result(result) for result in stored],
            diagnostics=diagnostics,
        )

    def get_result(self, result_id: str) -> dict:
        result = self._stored_result(result_id)
        return {"success": True, "item": self._public_result(result)}

    async def proxy_cover(self, result_id: str):
        return await self.stream_proxy.proxy_cover(self._stored_result(result_id))

    async def proxy_stream(self, result_id: str, range_header: str | None = None):
        return await self.stream_proxy.proxy_stream(self._stored_result(result_id), range_header)

    async def proxy_download(self, result_id: str):
        return await self.stream_proxy.proxy_download(self._stored_result(result_id))

    async def close(self) -> None:
        await self.browser.close()

    async def _search_browser_with_retries(self, search_keyword: str, limit: int):
        last_diagnostics = {}
        for attempt in range(1, 4):
            results, diagnostics = await self.browser.search(search_keyword, limit)
            diagnostics["attempt"] = attempt
            if results:
                return results, diagnostics
            last_diagnostics = diagnostics
        return [], last_diagnostics

    async def _translate(self, keyword: str) -> str:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    "https://translate.googleapis.com/translate_a/single",
                    params={"client": "gtx", "sl": "auto", "tl": "zh-CN", "dt": "t", "q": keyword},
                )
                response.raise_for_status()
                data = response.json()
                translated = "".join(part[0] for part in data[0] if part and part[0])
                return translated or keyword
        except Exception:
            return keyword

    def _stored_result(self, result_id: str) -> DouyinResult:
        result = self.store.get(result_id)
        if not result:
            raise DouyinSearchError(RESULT_EXPIRED, "Result is expired or does not exist.")
        return result

    def _public_result(self, result: DouyinResult) -> PublicDouyinResult:
        return PublicDouyinResult(
            result_id=result.result_id,
            douyin_aweme_id=result.douyin_aweme_id,
            title=result.title,
            description=result.description,
            author_name=result.author_name,
            author_id=result.author_id,
            cover_url=f"/api/douyin/results/{result.result_id}/cover",
            stream_url=f"/api/douyin/results/{result.result_id}/stream",
            download_url=f"/api/douyin/results/{result.result_id}/download",
            duration=result.duration,
            width=result.width,
            height=result.height,
            stats=result.stats,
            diagnostics={"has_stream": bool(result.stream_remote_url), "has_cover": bool(result.cover_remote_url)},
        )


douyin_service = DouyinSearchService()
