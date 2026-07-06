# API Contracts

Base path:

```text
/api/douyin
```

## Health

### GET `/api/douyin/health`

Returns module status.

```json
{
  "success": true,
  "module": "douyinsearch",
  "browser_ready": true,
  "cookie_file_exists": true
}
```

## Session Check

### POST `/api/douyin/session/check`

Validates whether the configured cookies can open Douyin without login failure or challenge.

```json
{
  "success": true,
  "state": "valid",
  "message": "Douyin session is usable."
}
```

Possible `state` values:

- `valid`
- `missing_cookie_file`
- `cookie_expired`
- `login_required`
- `challenge_required`
- `network_error`
- `unknown`

## Search

### POST `/api/douyin/search`

Request:

```json
{
  "keyword": "world cup reaction",
  "translate_to_chinese": true,
  "limit": 20,
  "cursor": null,
  "strategy": "auto"
}
```

`strategy` values:

- `auto`: try direct API when enabled, then browser fallback.
- `browser`: force Playwright browser search.
- `direct_api`: force direct Douyin web API.

Response:

```json
{
  "success": true,
  "keyword": "world cup reaction",
  "search_keyword": "世界杯反应",
  "strategy_used": "browser",
  "items": [
    {
      "result_id": "dyr_01J...",
      "douyin_aweme_id": "7350000000000000000",
      "title": "Video caption",
      "description": "Video caption",
      "author_name": "Author",
      "author_id": "sec_uid",
      "cover_url": "/api/douyin/results/dyr_01J.../cover",
      "stream_url": "/api/douyin/results/dyr_01J.../stream",
      "duration": 18.2,
      "width": 1080,
      "height": 1920,
      "stats": {
        "likes": 1000,
        "comments": 30,
        "shares": 20
      }
    }
  ],
  "next_cursor": null,
  "diagnostics": {
    "captured_api_response": true,
    "dom_fallback_used": false
  }
}
```

Error response:

```json
{
  "success": false,
  "error": {
    "code": "COOKIE_EXPIRED",
    "message": "Douyin cookie is expired or login is required.",
    "retryable": false
  }
}
```

## Result Metadata

### GET `/api/douyin/results/{result_id}`

Returns one normalized result from the TTL cache.

## Cover Proxy

### GET `/api/douyin/results/{result_id}/cover`

Proxies the cover image when a cover URL exists.

## Stream Proxy

### GET `/api/douyin/results/{result_id}/stream`

Streams playable video. Must support HTTP Range.

The stream endpoint should:

- Resolve or refresh the current Douyin video URL.
- Attach required headers/cookies.
- Return `206 Partial Content` for browser video seeking.
- Return typed errors when the result expired or media cannot be resolved.

## Error Codes

- `INVALID_KEYWORD`
- `MISSING_COOKIE_FILE`
- `COOKIE_EXPIRED`
- `LOGIN_REQUIRED`
- `CHALLENGE_REQUIRED`
- `NO_RESULTS`
- `DIRECT_API_FAILED`
- `BROWSER_SEARCH_FAILED`
- `RESULT_EXPIRED`
- `STREAM_RESOLVE_FAILED`
- `NETWORK_ERROR`
- `UNKNOWN_ERROR`
