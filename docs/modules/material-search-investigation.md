# Material Search Investigation Notes

## Test 1 Symptoms

- Search all was slow because each scene tried Douyin first, and Douyin often consumed the full timeout before Pinterest ran.
- `review` showed repeated errors because it returned all historical search task errors for a scene, not only the latest run.
- Pinterest preview did not play because candidate `stream_url` uses `/api/pinterest/results/{id}/stream`; that endpoint transcodes HLS to MP4 with FFmpeg and can hang before returning bytes.
- Pinterest `/media` returned quickly, but often as `application/vnd.apple.mpegurl`; Chrome video cannot reliably play that directly without an HLS player.
- Approve API itself was fast in isolation; the UI felt slow while Search all polling/rendering and video stream requests were still active.

## Douyin Failure Evidence

Diagnostic date: 2026-07-08.

- `DOUYIN_COOKIE_FILE` exists and loads 61 Netscape cookies.
- `jingxuan` can load and the page state detector returns `valid`.
- The search input and button exist:
  - `[data-e2e="searchbar-input"]`
  - `[data-e2e="searchbar-button"]`
- Typing into the input works, but clicking Search or pressing Enter does not navigate away from `/jingxuan`.
- Direct search URL loads:
  - `https://www.douyin.com/search/cat?type=video`
- The direct search page stays as a shell only:
  - body text only contains navigation and search tabs.
  - no `/aweme/v1/web/search/item/` or `/aweme/v1/web/general/search/single/` response is fired.
  - no `a[href*="/video/"]` result cards are rendered.
- Chinese keywords showed the same shell-only behavior, so this is not only an English keyword issue.
- Headful Chromium showed the same behavior as headless Chromium, so this is not only a headless mode issue.
- Console/page signals included Douyin security/verify scripts and `xgplayer sdk load timeout`.

## Likely Root Causes

1. The current browser path uses a fresh Playwright context plus cookies only. It does not use `DOUYIN_BROWSER_PROFILE_DIR`, persistent context, localStorage, IndexedDB, or a full browser storage state.
2. Douyin search appears to require more security/browser state than `jingxuan`. Cookie-only access can load the shell, but the search app does not issue the real search API request.
3. Some exported device/security cookies are expired, while session cookies are still valid. This can let basic pages work but leave the search security SDK in a bad state.
4. The VideoDesign material loop wraps each Douyin search in a 45 second timeout, but one failing browser search can exceed that before it reaches a clean `NO_RESULTS` diagnostic.
5. The preflight check is too shallow today: it validates page load and typing, but not whether a submitted search produces network results or DOM cards.

## Next Fix Direction

- Make Douyin optional per run when health/search preflight fails, so one broken source does not block all scenes.
- Upgrade Douyin health check to submit a keyword and require either a search API response or visible video cards.
- Use a persistent browser context/profile for Douyin instead of cookie-only fresh contexts.
- Clear old search task errors when a new material search starts.
- Shorten Douyin per-keyword timeout or move Pinterest first, so users get candidates quickly while Douyin is unstable.
- Treat shell-only search pages as a typed `DOUYIN_SEARCH_SHELL_ONLY` or `CHALLENGE_REQUIRED` style failure instead of waiting until timeout.

## Douyin Persistent Profile Update

Implementation direction applied after this investigation:

- Douyin BrowserClient now supports `DOUYIN_BROWSER_PROFILE_DIR` as a persistent Chromium profile.
- The persistent Douyin browser launches visible even if `DOUYIN_BROWSER_HEADLESS=true`, so the user can log in and solve captcha manually.
- Cookies from `DOUYIN_COOKIE_FILE` are still loaded into the persistent profile as a bootstrap step.
- Once login/captcha is completed in that Chromium window, Playwright keeps the same profile for later searches.
- Douyin preflight now submits a real search and requires either a captured search API response or visible video cards before reporting healthy.
- If search loads only the shell and no API/cards appear, Douyin returns a typed browser failure instead of waiting through repeated long retries.

## Douyin Login UX Update

Additional fix:

- If the user closes the visible Chromium window, the next health/search call detects the closed target and relaunches the persistent profile instead of failing with `BrowserContext.new_page: Target page, context or browser has been closed`.
- Douyin health/preflight opens a Douyin login entry page before running the real search check, so the user has a clearer place to log in or solve captcha.
- Douyin search also opens the login entry page on first empty-profile bootstrap before continuing to `jingxuan` and search.

## Douyin Login URL Correction

Follow-up fix:

- Direct `https://www.douyin.com/login` is not a usable browser login page; Douyin returns JSON `error_code=3` / `????`.
- The login bootstrap now opens normal Douyin pages and clicks a visible login entry (`??`) when present.
- JSON error pages are detected and skipped so health check does not leave the user on the wrong page.


## Douyin Search Health Timing Correction

Follow-up from live browser evidence on 2026-07-08:

- The visible Douyin browser can render search cards on `https://www.douyin.com/jingxuan/search/...`, but cards may appear after the old health timeout.
- The old detector only treated `/search/` and direct video anchors as success, so `/jingxuan/search/` pages with visible cards could still fail health.
- Health now recognizes both `/search/` and `/jingxuan/search/`, waits longer for search results, and reports success when visible result cards appear even before API parsing succeeds.
- The visible-card detector now looks for rendered card text with a duration plus author/date/wan-count signals, which matches the current Douyin search grid.