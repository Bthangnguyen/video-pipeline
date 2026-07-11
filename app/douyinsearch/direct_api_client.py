import random
import string
import sys
from pathlib import Path
from urllib.parse import quote, urlencode

import httpx

from app.douyinsearch.config import settings
from app.douyinsearch.cookies import cookie_header_from_file
from app.douyinsearch.cookies import load_cookies
from app.douyinsearch.errors import DIRECT_API_FAILED, DouyinSearchError
from app.douyinsearch.parser import parse_search_payload
from app.douyinsearch.schemas import SearchRequest


class DirectApiClient:
    SEARCH_ENDPOINT = "https://www.douyin.com/aweme/v1/web/general/search/single/"

    def __init__(self, signature_dir: Path = settings.signature_dir):
        self.signature_dir = signature_dir
        self.user_agent = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )

    async def search(self, request: SearchRequest, search_keyword: str | None = None):
        keyword = search_keyword or request.keyword
        cookie_values = self._cookie_values()
        params = self._build_params(keyword, request.limit, request.cursor, cookie_values, request.popular_first)
        params = self._sign_params(params)
        url = f"{self.SEARCH_ENDPOINT}?{urlencode(params)}"

        headers = {
            "User-Agent": self.user_agent,
            "Referer": f"https://www.douyin.com/jingxuan/search/{quote(keyword)}?type=general",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
        if settings.cookie_file.exists():
            cookie = cookie_header_from_file(settings.cookie_file)
            if cookie:
                headers["Cookie"] = cookie

        try:
            async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                payload = response.json()
        except Exception as exc:
            raise DouyinSearchError(DIRECT_API_FAILED, f"Direct API request failed: {exc}", retryable=True) from exc

        results = parse_search_payload(payload, request.limit)
        if not results:
            message = payload.get("status_msg") or payload.get("message") or "Direct API returned no parseable videos."
            raise DouyinSearchError(DIRECT_API_FAILED, str(message), retryable=True)

        return results, {
            "direct_api": True,
            "status_code": payload.get("status_code"),
            "has_more": payload.get("has_more"),
            "cursor": payload.get("cursor"),
            "popularity": {
                "requested": request.popular_first,
                "applied": request.popular_first,
                "method": "direct_api_request" if request.popular_first else "relevance",
                "publish_window_days": 180 if request.popular_first else 0,
            },
        }

    def _build_params(
        self,
        keyword: str,
        count: int,
        cursor: str | None,
        cookie_values: dict,
        popular_first: bool = False,
    ) -> dict:
        verify_fp = cookie_values.get("s_v_web_id", "")
        uifid = cookie_values.get("UIFID") or cookie_values.get("UIFID_TEMP") or ""
        return {
            "device_platform": "webapp",
            "aid": "6383",
            "channel": "channel_pc_web",
            "search_channel": "aweme_general",
            "keyword": keyword,
            "search_source": "normal_search",
            "query_correct_type": "1",
            "is_filter_search": "1" if popular_first else "0",
            "sort_type": "1" if popular_first else "0",
            "publish_time": "180" if popular_first else "0",
            "offset": cursor or "0",
            "count": str(max(count, 10)),
            "need_filter_settings": "1",
            "list_type": "single",
            "disable_rs": "0",
            "enable_history": "1",
            "support_dash": "1",
            "support_h265": "1",
            "pc_libra_divert": "Windows",
            "pc_client_type": "1",
            "version_code": "170400",
            "version_name": "17.4.0",
            "update_version_code": "170400",
            "cookie_enabled": "true",
            "screen_width": "1365",
            "screen_height": "900",
            "browser_language": "zh-CN",
            "browser_platform": "Win32",
            "browser_name": "Chrome",
            "browser_version": "124.0.0.0",
            "browser_online": "true",
            "engine_name": "Blink",
            "engine_version": "124.0.0.0",
            "os_name": "Windows",
            "os_version": "10",
            "cpu_core_num": "12",
            "device_memory": "8",
            "platform": "PC",
            "downlink": "10",
            "effective_type": "4g",
            "round_trip_time": "50",
            "webid": cookie_values.get("webid", "7654878572134483497"),
            "verifyFp": verify_fp,
            "fp": verify_fp,
            "uifid": uifid,
            "msToken": cookie_values.get("msToken", "") or self._ms_token(),
        }

    def _sign_params(self, params: dict) -> dict:
        abogus_path = self.signature_dir / "abogus.py"
        if not abogus_path.exists():
            return params
        sys.path.insert(0, str(self.signature_dir))
        try:
            from abogus import ABogus

            signed = dict(params)
            signed["a_bogus"] = ABogus().get_value(signed)
            return signed
        except Exception:
            return params
        finally:
            try:
                sys.path.remove(str(self.signature_dir))
            except ValueError:
                pass

    def _ms_token(self) -> str:
        alphabet = string.ascii_letters + string.digits
        return "".join(random.choice(alphabet) for _ in range(126)) + "=="

    def _cookie_values(self) -> dict:
        if not settings.cookie_file.exists():
            return {}
        return {cookie["name"]: cookie["value"] for cookie in load_cookies(settings.cookie_file)}
