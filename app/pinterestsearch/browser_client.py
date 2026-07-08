import asyncio
from pathlib import Path
from urllib.parse import quote

from app.pinterestsearch.cookies import load_cookies
from app.pinterestsearch.errors import (
    BROWSER_SEARCH_FAILED,
    CHALLENGE_REQUIRED,
    LOGIN_REQUIRED,
    MISSING_COOKIE_FILE,
    PinterestSearchError,
)
from app.pinterestsearch.parser import parse_api_payloads, parse_dom_cards
from app.pinterestsearch.schemas import PinterestResult, SearchRequest


class BrowserClient:
    def __init__(self, cookie_file: Path, headless: bool, debug: bool):
        self.cookie_file = cookie_file
        self.headless = headless
        self.debug = debug
        self._playwright = None
        self._browser = None

    async def close(self) -> None:
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None

    async def check_session(self) -> dict:
        if not self.cookie_file.exists():
            return {"success": False, "state": "missing_cookie_file", "message": "Cookie file does not exist."}
        context = await self._new_context()
        page = await context.new_page()
        try:
            await page.goto("https://www.pinterest.com/", wait_until="domcontentloaded", timeout=45000)
            await page.wait_for_timeout(2000)
            state = await self._detect_page_state(page)
            return {"success": state == "valid", "state": state, "message": self._session_message(state)}
        except Exception as exc:
            return {"success": False, "state": "network_error", "message": str(exc)}
        finally:
            await context.close()

    async def search(self, request: SearchRequest) -> tuple[list[PinterestResult], dict]:
        if not self.cookie_file.exists():
            raise PinterestSearchError(MISSING_COOKIE_FILE, "Cookie file does not exist.")

        context = await self._new_context()
        page = await context.new_page()
        try:
            state = "valid"
            results: list[PinterestResult] = []
            attempts: list[dict] = []
            paths = self._search_paths(request.keyword, request.media_type)
            for index, url in enumerate(paths, start=1):
                payloads: list[dict] = []
                pending_payloads: list[asyncio.Task] = []

                def on_response(response):
                    if "BaseSearchResource/get" in response.url:
                        pending_payloads.append(asyncio.create_task(self._capture_json_response(response, payloads)))

                page.on("response", on_response)
                await page.goto(url, wait_until="domcontentloaded", timeout=45000)
                await page.wait_for_timeout(2500)
                state = await self._detect_page_state(page)
                if state == "challenge_required":
                    raise PinterestSearchError(CHALLENGE_REQUIRED, "Pinterest challenge or captcha is required.")
                if state == "login_required":
                    raise PinterestSearchError(LOGIN_REQUIRED, "Pinterest login is required or cookies are expired.")

                await self._scroll_for_results(page)
                await page.wait_for_timeout(1000)
                if pending_payloads:
                    await asyncio.gather(*pending_payloads, return_exceptions=True)
                cards = await self._extract_dom_cards(page)
                api_results = parse_api_payloads(
                    payloads,
                    request.limit,
                    request.media_type,
                    request.aspect_ratio,
                    request.aspect_tolerance,
                )
                dom_results = parse_dom_cards(
                    cards,
                    request.limit,
                    request.media_type,
                    request.aspect_ratio,
                    request.aspect_tolerance,
                )
                results = self._merge_results(results, api_results, dom_results)
                attempts.append(
                    {
                        "url": url,
                        "api_payloads": len(payloads),
                        "api_results": len(api_results),
                        "dom_cards_extracted": len(cards),
                        "dom_results": len(dom_results),
                    }
                )
                page.remove_listener("response", on_response)
                if len(results) >= request.limit:
                    return results, {
                        "browser_search_url": url,
                        "search_attempt": index,
                        "cards_extracted": sum(attempt["dom_cards_extracted"] for attempt in attempts),
                        "api_payloads": sum(attempt["api_payloads"] for attempt in attempts),
                        "state": state,
                        "attempts": attempts,
                    }

            return results, {
                "cards_extracted": sum(attempt["dom_cards_extracted"] for attempt in attempts),
                "api_payloads": sum(attempt["api_payloads"] for attempt in attempts),
                "state": state,
                "search_urls": paths,
                "attempts": attempts,
            }
        except PinterestSearchError:
            raise
        except Exception as exc:
            raise PinterestSearchError(BROWSER_SEARCH_FAILED, f"Browser search failed: {exc}", retryable=True) from exc
        finally:
            await context.close()

    async def _browser_instance(self):
        if self._browser and self._browser.is_connected():
            return self._browser
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise PinterestSearchError(BROWSER_SEARCH_FAILED, "Playwright is not installed.") from exc
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=self.headless,
            args=["--disable-blink-features=AutomationControlled", "--disable-dev-shm-usage"],
        )
        return self._browser

    async def _new_context(self):
        browser = await self._browser_instance()
        context = await browser.new_context(
            viewport={"width": 1365, "height": 900},
            locale="en-US",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
        )
        cookies = load_cookies(self.cookie_file)
        if cookies:
            await context.add_cookies(cookies)
        return context

    async def _detect_page_state(self, page) -> str:
        text = (await page.locator("body").inner_text(timeout=8000)).lower()
        url = page.url.lower()
        if any(token in text or token in url for token in ("captcha", "challenge", "verify you are")):
            return "challenge_required"
        login_tokens = ("log in", "sign up", "login", "sign in")
        if "/login" in url or (any(token in text for token in login_tokens) and "pinterest" in text):
            if not await page.locator('a[href*="/pin/"]').count():
                return "login_required"
        return "valid"

    def _search_paths(self, keyword: str, media_type: str) -> list[str]:
        queries = self._query_variants(keyword, media_type)
        urls: list[str] = []
        if media_type == "video":
            urls.extend(f"https://www.pinterest.com/search/videos/?q={quote(query)}&rs=typed" for query in queries)
        urls.extend(f"https://www.pinterest.com/search/pins/?q={quote(query)}&rs=typed" for query in queries)
        return list(dict.fromkeys(urls))

    def _query_variants(self, keyword: str, media_type: str) -> list[str]:
        query = " ".join(keyword.strip().split())
        variants = [query] if query else []
        if media_type in {"video", "image"}:
            generic_tokens = {"video", "videos"} if media_type == "video" else {"image", "images", "photo", "photos"}
            cleaned = " ".join(token for token in query.split() if token.lower() not in generic_tokens).strip()
            if cleaned and cleaned not in variants:
                variants.append(cleaned)
        return variants

    async def _scroll_for_results(self, page) -> None:
        for _ in range(4):
            await page.mouse.wheel(0, 1400)
            await page.wait_for_timeout(700)

    async def _extract_dom_cards(self, page) -> list[dict]:
        last_error = None
        for _ in range(3):
            try:
                return await page.evaluate(
                    """
                    () => Array.from(document.querySelectorAll('a[href*="/pin/"]')).slice(0, 160).map((a) => {
                        const root = a.closest('[data-test-id], [role="listitem"], div') || a;
                        const img = root.querySelector('img') || a.querySelector('img');
                        const video = root.querySelector('video') || a.querySelector('video');
                        const source = video?.querySelector('source');
                        const mediaRect = (video || img || root).getBoundingClientRect();
                        const title = a.getAttribute('aria-label') || img?.alt || root.innerText || '';
                        const profile = root.querySelector('a[href*="/"]');
                        return {
                            href: a.href,
                            pin_id: (a.href.match(/\\/pin\\/(\\d+)/) || [])[1] || '',
                            title,
                            description: img?.alt || '',
                            image_url: img?.currentSrc || img?.src || '',
                            video_url: video?.currentSrc || video?.src || source?.src || '',
                            video_poster: video?.poster || '',
                            width: video?.videoWidth || img?.naturalWidth || img?.width || Math.round(mediaRect.width) || 0,
                            height: video?.videoHeight || img?.naturalHeight || img?.height || Math.round(mediaRect.height) || 0,
                            author_name: profile?.innerText || '',
                            author_url: profile?.href || ''
                        };
                    })
                    """
                )
            except Exception as exc:
                last_error = exc
                message = str(exc).lower()
                if "execution context was destroyed" not in message and "navigation" not in message:
                    raise
                try:
                    await page.wait_for_load_state("domcontentloaded", timeout=10000)
                except Exception:
                    pass
                await page.wait_for_timeout(800)
        if last_error:
            raise last_error
        return []

    async def _capture_json_response(self, response, payloads: list[dict]) -> None:
        try:
            payloads.append(await response.json())
        except Exception:
            return

    def _merge_results(
        self,
        current: list[PinterestResult],
        api_results: list[PinterestResult],
        dom_results: list[PinterestResult],
    ) -> list[PinterestResult]:
        merged: list[PinterestResult] = []
        seen: set[str] = set()
        for result in [*current, *api_results, *dom_results]:
            key = result.pin_id or result.media_remote_url or result.cover_remote_url
            if not key or key in seen:
                continue
            seen.add(key)
            merged.append(result)
        return merged

    def _session_message(self, state: str) -> str:
        return {
            "valid": "Pinterest session is usable.",
            "missing_cookie_file": "Cookie file does not exist.",
            "login_required": "Pinterest login is required or cookies are expired.",
            "challenge_required": "Pinterest challenge or captcha is required.",
            "network_error": "Cannot reach Pinterest.",
        }.get(state, "Unknown session state.")
