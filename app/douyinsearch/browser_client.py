import asyncio
import time
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


LOGIN_URLS = (
    "https://www.douyin.com/?enter_from=login",
    "https://www.douyin.com/jingxuan",
    "https://www.douyin.com",
)

SEARCH_PATH_TOKENS = ("/search/", "/jingxuan/search/")


class BrowserClient:
    def __init__(self, cookie_file: Path, headless: bool, debug: bool, profile_dir: Path | None = None):
        self.cookie_file = cookie_file
        self.headless = headless
        self.debug = debug
        self.profile_dir = profile_dir
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self._search_lock = asyncio.Lock()

    async def close(self) -> None:
        if self._context:
            await self._context.close()
            self._context = None
            self._page = None
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None

    async def check_session(self) -> dict:
        if not self.cookie_file.exists():
            return {"success": False, "state": "missing_cookie_file", "message": "Cookie file does not exist."}
        context, page = await self._new_page_context()
        try:
            if self.profile_dir:
                await self._open_login_page(page)
                state = await self._detect_page_state(page)
                await self._wait_for_manual_session(page, state)
            await page.goto("https://www.douyin.com", wait_until="domcontentloaded", timeout=45000)
            await page.wait_for_timeout(2500)
            state = await self._detect_page_state(page)
            state = await self._wait_for_manual_session(page, state)
            return {
                "success": state == "valid",
                "state": state,
                "message": self._session_message(state),
                "profile_dir": str(self.profile_dir) if self.profile_dir else "",
            }
        except Exception as exc:
            return {"success": False, "state": "network_error", "message": str(exc)}
        finally:
            await self._release_context(context)

    async def preflight_check(self, keyword: str = "cat") -> dict:
        checks = []
        if not self.cookie_file.exists():
            checks.append(_check("cookie_file", False, "Cookie file does not exist."))
            return {"success": False, "source": "douyinsearch", "state": "missing_cookie_file", "checks": checks}
        checks.append(_check("cookie_file", True, str(self.cookie_file)))
        if self.profile_dir:
            checks.append(_check("browser_profile", True, str(self.profile_dir), {"visible": True}))

        context, page = await self._new_page_context()
        captured_payloads: list[dict] = []
        state = "unknown"

        async def capture_response(response):
            if not self._is_search_response(response.url):
                return
            try:
                captured_payloads.append(await response.json())
            except Exception:
                return

        response_handler = lambda response: asyncio.create_task(capture_response(response))
        page.on("response", response_handler)
        try:
            if self.profile_dir:
                login_detail = await self._open_login_page(page)
                checks.append(_check("open_login", True, "Opened Douyin login page. Log in or solve captcha in the Chromium window if prompted.", login_detail))
                state = await self._detect_page_state(page)
                state = await self._wait_for_manual_session(page, state)
            if "douyin.com" not in page.url:
                await page.goto("https://www.douyin.com/jingxuan", wait_until="domcontentloaded", timeout=45000)
                await page.wait_for_timeout(1500)
            else:
                await page.wait_for_timeout(800)
            checks.append(_check("load_jingxuan", True, "Loaded https://www.douyin.com/jingxuan."))
            state = await self._detect_page_state(page)
            state = await self._wait_for_manual_session(page, state)
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
                searched_with_input = await self._submit_search(page, input_locator, button_locator)
                if not searched_with_input or (not self._is_search_page(page.url) and not captured_payloads):
                    await page.goto(f"https://www.douyin.com/search/{quote(keyword)}?type=video", wait_until="domcontentloaded", timeout=45000)
                results, diagnostics = await self._wait_for_results(page, captured_payloads, 1, attempts=30)
                has_visible_cards = diagnostics.get("visible_result_card_count", 0) > 0
                search_ok = bool(results) or has_visible_cards
                checks.append(
                    _check(
                        "search_results",
                        search_ok,
                        "Douyin search returned visible video cards." if search_ok else "Search page loaded but no Douyin API results or video cards appeared yet.",
                        diagnostics,
                    )
                )
            else:
                checks.append(_check("input_search", False, "Search input or button was not found."))
        except Exception as exc:
            checks.append(_check("network_douyin", False, str(exc)))
        finally:
            self._remove_response_handler(page, response_handler)
            await self._release_context(context)
        return {"success": all(item["ok"] for item in checks), "source": "douyinsearch", "state": state, "checks": checks}

    async def search(self, keyword: str, limit: int) -> tuple[list[DouyinResult], dict]:
        if self.profile_dir:
            async with self._search_lock:
                return await self._search(keyword, limit)
        return await self._search(keyword, limit)

    async def _search(self, keyword: str, limit: int) -> tuple[list[DouyinResult], dict]:
        if not self.cookie_file.exists():
            raise DouyinSearchError(MISSING_COOKIE_FILE, "Cookie file does not exist.")

        context, page = await self._new_page_context()
        captured_payloads: list[dict] = []

        async def capture_response(response):
            if not self._is_search_response(response.url):
                return
            try:
                captured_payloads.append(await response.json())
            except Exception:
                return

        response_handler = lambda response: asyncio.create_task(capture_response(response))
        page.on("response", response_handler)

        try:
            if self.profile_dir and self._needs_login_bootstrap():
                await self._open_login_page(page)
                state = await self._detect_page_state(page)
                await self._wait_for_manual_session(page, state)
            if "douyin.com" not in page.url:
                await page.goto("https://www.douyin.com/jingxuan", wait_until="domcontentloaded", timeout=45000)
                await page.wait_for_timeout(1500)
            else:
                await page.wait_for_timeout(800)
            state = await self._detect_page_state(page)
            state = await self._wait_for_manual_session(page, state)
            if state == "challenge_required":
                raise DouyinSearchError(CHALLENGE_REQUIRED, "Douyin challenge or captcha is required.")
            if state == "login_required":
                raise DouyinSearchError(LOGIN_REQUIRED, "Douyin login is required or cookies are expired.")

            searched_with_input = await self._try_search_input(page, keyword)
            if searched_with_input:
                await page.wait_for_timeout(2500)
            if not searched_with_input or (not self._is_search_page(page.url) and not captured_payloads):
                url = f"https://www.douyin.com/search/{quote(keyword)}?type=video"
                await page.goto(url, wait_until="domcontentloaded", timeout=45000)

            results, diagnostics = await self._wait_for_results(page, captured_payloads, limit)
            if results:
                return results, diagnostics
            if diagnostics.get("search_shell_only"):
                raise DouyinSearchError(
                    BROWSER_SEARCH_FAILED,
                    "Douyin search page loaded, but no search API response or video cards appeared. The persistent browser profile may need manual login or captcha verification.",
                    retryable=True,
                )

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
            self._remove_response_handler(page, response_handler)
            await self._release_context(context)

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

    async def _new_page_context(self):
        context = await self._new_context()
        if self.profile_dir:
            try:
                page = await self._persistent_page(context)
                return context, page
            except Exception as exc:
                if not self._is_target_closed_error(exc):
                    raise
                self._context = None
                self._page = None
                context = await self._new_context()
                page = await self._persistent_page(context)
                return context, page
        try:
            page = await context.new_page()
            return context, page
        except Exception:
            await context.close()
            raise

    async def _persistent_page(self, context):
        if self._page and not self._page.is_closed():
            await self._close_extra_persistent_pages(self._page)
            return self._page

        pages = [page for page in context.pages if not page.is_closed()]
        douyin_pages = [page for page in pages if "douyin.com" in page.url]
        page = douyin_pages[-1] if douyin_pages else (pages[0] if pages else await context.new_page())
        self._page = page
        await self._close_extra_persistent_pages(page)
        return page

    async def _close_extra_persistent_pages(self, keep_page) -> None:
        if not self._context:
            return
        for page in list(self._context.pages):
            if page is keep_page or page.is_closed():
                continue
            url = page.url or ""
            if url == "about:blank" or "douyin.com" in url:
                try:
                    await page.close()
                except Exception:
                    pass

    async def _new_context(self):
        if self.profile_dir:
            return await self._persistent_context()
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

    async def _persistent_context(self):
        if self._context:
            try:
                _ = self._context.pages
                return self._context
            except Exception:
                self._context = None
                self._page = None
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise DouyinSearchError(BROWSER_SEARCH_FAILED, "Playwright is not installed.") from exc
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        if not self._playwright:
            self._playwright = await async_playwright().start()
        self._page = None
        self._context = await self._playwright.chromium.launch_persistent_context(
            str(self.profile_dir),
            headless=False,
            viewport={"width": 1365, "height": 900},
            locale="zh-CN",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            args=["--disable-blink-features=AutomationControlled", "--disable-dev-shm-usage"],
        )
        cookies = load_cookies(self.cookie_file)
        if cookies:
            await self._context.add_cookies(cookies)
        return self._context

    async def _release_context(self, context) -> None:
        if context is self._context:
            return
        await context.close()

    def _remove_response_handler(self, page, handler) -> None:
        try:
            page.remove_listener("response", handler)
        except Exception:
            pass

    async def _open_login_page(self, page) -> dict:
        last_error = ""
        for url in LOGIN_URLS:
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=45000)
                await page.wait_for_timeout(2500)
                if await self._is_json_error_page(page):
                    last_error = "Douyin returned a JSON error page instead of login UI."
                    continue
                click_detail = await self._click_login_entry(page)
                return {"target_url": url, "current_url": page.url, **click_detail}
            except Exception as exc:
                last_error = str(exc)
        raise DouyinSearchError(BROWSER_SEARCH_FAILED, f"Could not open Douyin login entry page: {last_error}", retryable=True)

    async def _click_login_entry(self, page) -> dict:
        return await page.evaluate(
            """
            () => {
                const loginPattern = new RegExp("\\u767b\\u5f55|\\u767b\\u5165|\\u767b\\u9646|log in|login", "i");
                const isVisible = (el) => {
                    const style = window.getComputedStyle(el);
                    const rect = el.getBoundingClientRect();
                    return style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0;
                };
                const elements = Array.from(document.querySelectorAll('button,a,div,span'));
                const candidate = elements.find((el) => {
                    const text = `${el.innerText || el.textContent || ''} ${el.getAttribute('aria-label') || ''}`.trim();
                    return text && loginPattern.test(text) && isVisible(el);
                });
                if (!candidate) return { clicked_login: false };
                const text = (candidate.innerText || candidate.textContent || candidate.getAttribute('aria-label') || '').trim().slice(0, 80);
                candidate.click();
                return { clicked_login: true, login_text: text };
            }
            """
        )

    async def _is_json_error_page(self, page) -> bool:
        try:
            body = (await page.locator("body").inner_text(timeout=3000)).strip()
        except Exception:
            return False
        return body.startswith("{") and "error_code" in body

    def _needs_login_bootstrap(self) -> bool:
        if not self.profile_dir or not self.profile_dir.exists():
            return True
        try:
            return not any(self.profile_dir.iterdir())
        except OSError:
            return True

    def _is_target_closed_error(self, exc: Exception) -> bool:
        message = str(exc).lower()
        return "has been closed" in message or "target page" in message or "target closed" in message

    async def _detect_page_state(self, page) -> str:
        text = (await page.locator("body").inner_text(timeout=5000)).lower()
        url = page.url.lower()
        if any(token in text or token in url for token in ("captcha", "verify", "\u9a8c\u8bc1\u7801", "\u9a8c\u8bc1")):
            return "challenge_required"
        login_path_tokens = ("/login", "login.douyin.com", "sso.douyin.com")
        login_wall_tokens = ("\u767b\u5f55\u540e", "\u8bf7\u5148\u767b\u5f55", "login required")
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
                if await self._submit_search(page, input_locator, button_locator):
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

    async def _submit_search(self, page, input_locator, button_locator) -> bool:
        await page.wait_for_timeout(500)
        await button_locator.click(timeout=5000)
        await page.wait_for_timeout(2500)
        if self._is_search_page(page.url):
            return True
        await input_locator.press("Enter", timeout=3000)
        await page.wait_for_timeout(2500)
        return self._is_search_page(page.url)

    async def _extract_dom_cards(self, page) -> list[dict]:
        return await page.evaluate(
            """
            () => {
                const anchors = Array.from(document.querySelectorAll('a[href*="/video/"], a[href*="/share/video/"], a[href*="modal_id="]'));
                const seen = new Set();
                return anchors.slice(0, 120).map((a) => {
                    const root = a.closest('[data-e2e], article, li, div') || a;
                    const img = root.querySelector('img') || a.querySelector('img');
                    const href = a.href || a.getAttribute('href') || '';
                    const title = root.innerText || a.innerText || a.getAttribute('title') || '';
                    const key = href || title;
                    if (!key || seen.has(key)) return null;
                    seen.add(key);
                    return {
                        href,
                        title,
                        cover_url: img?.src || img?.getAttribute('src') || ''
                    };
                }).filter(Boolean);
            }
            """
        )

    async def _visible_result_card_count(self, page) -> int:
        return await page.evaluate(
            """
            () => {
                const isVisible = (el) => {
                    const style = window.getComputedStyle(el);
                    const rect = el.getBoundingClientRect();
                    return style.visibility !== 'hidden' && style.display !== 'none' && rect.width >= 120 && rect.height >= 160;
                };
                const cardLike = Array.from(document.querySelectorAll('a, article, li, div')).filter((el) => {
                    if (!isVisible(el)) return false;
                    const text = (el.innerText || el.textContent || '').trim();
                    if (text.length < 8) return false;
                    const hasDuration = /\\b\\d{1,2}:\\d{2}\\b/.test(text);
                    const hasAuthor = text.includes('@') || text.includes('\\u00b7');
                    const hasLikeText = text.includes('\\u4e07');
                    return hasDuration && (hasAuthor || hasLikeText);
                });
                return Math.min(cardLike.length, 80);
            }
            """
        )

    async def _wait_for_results(self, page, captured_payloads: list[dict], limit: int, attempts: int = 15) -> tuple[list[DouyinResult], dict]:
        last_card_count = 0
        last_visible_card_count = 0
        for _ in range(attempts):
            for payload in captured_payloads:
                results = parse_search_payload(payload, limit)
                if results:
                    return results, {"captured_api_response": True, "dom_fallback_used": False}

            cards = await self._extract_dom_cards(page)
            last_card_count = len(cards)
            last_visible_card_count = await self._visible_result_card_count(page)
            results = parse_dom_cards(cards, limit)
            if results:
                return results, {"captured_api_response": False, "dom_fallback_used": True}

            await page.wait_for_timeout(1000)

        return [], {
            "captured_api_response": bool(captured_payloads),
            "dom_fallback_used": True,
            "dom_card_count": last_card_count,
            "visible_result_card_count": last_visible_card_count,
            "search_shell_only": self._is_search_page(page.url) and not captured_payloads and last_card_count == 0 and last_visible_card_count == 0,
        }

    async def _wait_for_manual_session(self, page, state: str, timeout_seconds: int = 180) -> str:
        if state == "valid" or not self.profile_dir:
            return state
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            await page.wait_for_timeout(3000)
            state = await self._detect_page_state(page)
            if state == "valid":
                return state
        return state

    def _is_search_page(self, url: str) -> bool:
        return any(token in url for token in SEARCH_PATH_TOKENS)

    def _is_search_response(self, url: str) -> bool:
        return any(
            endpoint in url
            for endpoint in (
                "/aweme/v1/web/search/item/",
                "/aweme/v1/web/general/search/single/",
            )
        )

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
