import asyncio
from pathlib import Path
from urllib.parse import quote

from app.douyinsearch.cookies import load_cookies
from app.douyinsearch.errors import (
    BROWSER_SEARCH_FAILED,
    CHALLENGE_REQUIRED,
    LOGIN_REQUIRED,
    MISSING_COOKIE_FILE,
    DouyinSearchError,
)
from app.douyinsearch.parser import parse_dom_cards, parse_search_payload
from app.douyinsearch.schemas import DouyinResult


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
            await page.goto("https://www.douyin.com", wait_until="domcontentloaded", timeout=45000)
            await page.wait_for_timeout(2500)
            state = await self._detect_page_state(page)
            return {"success": state == "valid", "state": state, "message": self._session_message(state)}
        except Exception as exc:
            return {"success": False, "state": "network_error", "message": str(exc)}
        finally:
            await context.close()

    async def preflight_check(self, keyword: str = "cat") -> dict:
        checks = []
        if not self.cookie_file.exists():
            checks.append(_check("cookie_file", False, "Cookie file does not exist."))
            return {"success": False, "source": "douyinsearch", "state": "missing_cookie_file", "checks": checks}
        checks.append(_check("cookie_file", True, str(self.cookie_file)))

        context = await self._new_context()
        page = await context.new_page()
        state = "unknown"
        try:
            await page.goto("https://www.douyin.com/jingxuan", wait_until="domcontentloaded", timeout=45000)
            await page.wait_for_timeout(1500)
            checks.append(_check("load_jingxuan", True, "Loaded https://www.douyin.com/jingxuan."))
            state = await self._detect_page_state(page)
            checks.append(_check("anti_bot", state == "valid", self._session_message(state), {"state": state}))

            input_locator = page.locator('[data-e2e="searchbar-input"]').first
            button_locator = page.locator('[data-e2e="searchbar-button"]').first
            input_ready = await input_locator.count() > 0 and await button_locator.count() > 0
            if input_ready:
                await input_locator.click(timeout=5000)
                await input_locator.press("Control+A", timeout=3000)
                await input_locator.press("Backspace", timeout=3000)
                await input_locator.type(keyword, delay=30, timeout=8000)
                checks.append(_check("input_search", True, f"Search input accepted '{keyword}'."))
            else:
                checks.append(_check("input_search", False, "Search input or button was not found."))
        except Exception as exc:
            checks.append(_check("network_douyin", False, str(exc)))
        finally:
            await context.close()
        return {"success": all(item["ok"] for item in checks), "source": "douyinsearch", "state": state, "checks": checks}

    async def search(self, keyword: str, limit: int) -> tuple[list[DouyinResult], dict]:
        if not self.cookie_file.exists():
            raise DouyinSearchError(MISSING_COOKIE_FILE, "Cookie file does not exist.")

        context = await self._new_context()
        page = await context.new_page()
        captured_payloads: list[dict] = []

        async def capture_response(response):
            search_endpoints = (
                "/aweme/v1/web/search/item/",
                "/aweme/v1/web/general/search/single/",
            )
            if not any(endpoint in response.url for endpoint in search_endpoints):
                return
            try:
                captured_payloads.append(await response.json())
            except Exception:
                return

        page.on("response", lambda response: asyncio.create_task(capture_response(response)))

        try:
            await page.goto("https://www.douyin.com/jingxuan", wait_until="domcontentloaded", timeout=45000)
            await page.wait_for_timeout(1500)
            state = await self._detect_page_state(page)
            if state == "challenge_required":
                raise DouyinSearchError(CHALLENGE_REQUIRED, "Douyin challenge or captcha is required.")
            if state == "login_required":
                raise DouyinSearchError(LOGIN_REQUIRED, "Douyin login is required or cookies are expired.")

            searched_with_input = await self._try_search_input(page, keyword)
            if searched_with_input:
                await page.wait_for_timeout(2500)
            if not searched_with_input or ("/search/" not in page.url and not captured_payloads):
                url = f"https://www.douyin.com/search/{quote(keyword)}?type=video"
                await page.goto(url, wait_until="domcontentloaded", timeout=45000)

            results, diagnostics = await self._wait_for_results(page, captured_payloads, limit)
            if results:
                return results, diagnostics

            captured_payloads.clear()
            retry_url = f"https://www.douyin.com/search/{quote(keyword)}?type=video"
            await page.goto(retry_url, wait_until="domcontentloaded", timeout=45000)
            results, diagnostics = await self._wait_for_results(page, captured_payloads, limit)
            diagnostics["retry_used"] = True
            return results, diagnostics
        except DouyinSearchError:
            raise
        except Exception as exc:
            raise DouyinSearchError(BROWSER_SEARCH_FAILED, f"Browser search failed: {exc}", retryable=True) from exc
        finally:
            await context.close()

    async def _browser_instance(self):
        if self._browser and self._browser.is_connected():
            return self._browser
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise DouyinSearchError(BROWSER_SEARCH_FAILED, "Playwright is not installed.") from exc
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
            locale="zh-CN",
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
        text = (await page.locator("body").inner_text(timeout=5000)).lower()
        url = page.url.lower()
        if any(token in text or token in url for token in ("captcha", "verify", "验证码", "验证")):
            return "challenge_required"
        login_path_tokens = ("/login", "login.douyin.com", "sso.douyin.com")
        login_wall_tokens = ("登录后", "请先登录", "login required")
        if any(token in url for token in login_path_tokens) or any(token in text for token in login_wall_tokens):
            return "login_required"
        return "valid"

    async def _try_search_input(self, page, keyword: str) -> bool:
        for attempt in range(3):
            try:
                if "douyin.com/jingxuan" not in page.url:
                    await page.goto("https://www.douyin.com/jingxuan", wait_until="domcontentloaded", timeout=45000)
                await page.wait_for_timeout(2500)

                input_locator = page.locator('[data-e2e="searchbar-input"]').first
                button_locator = page.locator('[data-e2e="searchbar-button"]').first
                if await input_locator.count() == 0 or await button_locator.count() == 0:
                    continue

                await input_locator.click(timeout=5000)
                await input_locator.press("Control+A", timeout=3000)
                await input_locator.press("Backspace", timeout=3000)
                await input_locator.type(keyword, delay=100, timeout=10000)
                await page.wait_for_timeout(500)
                await button_locator.click(timeout=5000)
                await page.wait_for_timeout(2500)

                if "/search/" in page.url:
                    return True

                await input_locator.press("Enter", timeout=3000)
                await page.wait_for_timeout(2500)
                if "/search/" in page.url:
                    return True

                if attempt < 2:
                    await page.goto("https://www.douyin.com/jingxuan", wait_until="domcontentloaded", timeout=45000)
            except Exception:
                if attempt < 2:
                    try:
                        await page.goto("https://www.douyin.com/jingxuan", wait_until="domcontentloaded", timeout=45000)
                    except Exception:
                        pass
                continue
        return False

    async def _extract_dom_cards(self, page) -> list[dict]:
        return await page.evaluate(
            """
            () => Array.from(document.querySelectorAll('a[href*="/video/"]')).slice(0, 80).map((a) => {
                const img = a.querySelector('img') || a.closest('[data-e2e]')?.querySelector('img');
                return {
                    href: a.href,
                    title: a.innerText || a.getAttribute('title') || '',
                    cover_url: img?.src || ''
                };
            })
            """
        )

    async def _wait_for_results(self, page, captured_payloads: list[dict], limit: int) -> tuple[list[DouyinResult], dict]:
        for _ in range(15):
            for payload in captured_payloads:
                results = parse_search_payload(payload, limit)
                if results:
                    return results, {"captured_api_response": True, "dom_fallback_used": False}

            cards = await self._extract_dom_cards(page)
            results = parse_dom_cards(cards, limit)
            if results:
                return results, {"captured_api_response": False, "dom_fallback_used": True}

            await page.wait_for_timeout(1000)

        return [], {"captured_api_response": bool(captured_payloads), "dom_fallback_used": True}

    def _session_message(self, state: str) -> str:
        return {
            "valid": "Douyin session is usable.",
            "missing_cookie_file": "Cookie file does not exist.",
            "login_required": "Douyin login is required or cookies are expired.",
            "challenge_required": "Douyin challenge or captcha is required.",
            "network_error": "Cannot reach Douyin.",
        }.get(state, "Unknown session state.")


def _check(name: str, ok: bool, message: str, detail: dict | None = None) -> dict:
    return {"name": name, "ok": ok, "message": message, "detail": detail or {}}
