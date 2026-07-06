# Implementation Plan

## Phase 1: Module Skeleton

- Create FastAPI app.
- Add `douyinsearch` package.
- Add config loader.
- Add typed schemas and errors.
- Add health endpoint.
- Add minimal static test UI.

Acceptance:

- Server starts.
- `/api/douyin/health` returns module status.
- Test UI loads.

## Phase 2: Cookie And Browser Session

- Implement cookie loader for plain cookie string, exported JSON, and Playwright storage state.
- Implement Playwright context manager.
- Implement session check endpoint.
- Detect missing cookies, login required, and challenge pages.

Acceptance:

- `/api/douyin/session/check` reports a typed state.
- Browser can open Douyin with configured cookies.

## Phase 3: Browser Search

- Implement keyword search through Douyin UI search input.
- Capture `/aweme/v1/web/search/item/` network responses.
- Parse response payload into normalized results.
- Add DOM card fallback when response capture fails.
- Add result TTL store.

Acceptance:

- `/api/douyin/search` with `strategy=browser` returns normalized video results.
- Empty/failure states return typed errors.

## Phase 4: Direct API Fast Path

- Implement optional direct API client.
- Add config flag `DOUYIN_USE_DIRECT_API`.
- Generate or reuse required request signatures where possible.
- Fall back to browser strategy under `strategy=auto`.

Acceptance:

- `strategy=direct_api` can be tested independently.
- `strategy=auto` still works when direct API fails.

## Phase 5: Stream Proxy

- Implement result stream resolver.
- Implement `/api/douyin/results/{result_id}/stream`.
- Support HTTP Range requests.
- Attach Douyin headers/cookies.
- Implement cover proxy.

Acceptance:

- Search result videos play in the module UI.
- Browser seeking works for playable streams.
- Expired results return `RESULT_EXPIRED`.

## Phase 6: Diagnostics And Hardening

- Add structured logs.
- Add search diagnostics in response.
- Add screenshots/html dump for failed browser search in debug mode.
- Add retry/backoff for network operations.
- Add unit tests for parsing and cookie loading.
- Add integration test stubs for browser search.

Acceptance:

- Failures are debuggable without reading raw Playwright logs.
- Parser/cookie tests pass.

## Done Definition

The module is done when:

- A user can configure cookies.
- A user can search Douyin from the test UI.
- Results display with cover/title/author.
- A selected result plays through backend stream proxy.
- API responses are stable enough for a future module to consume.
