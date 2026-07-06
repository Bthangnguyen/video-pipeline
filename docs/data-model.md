# Data Model

## Overview

The module only needs short-lived search data. V1 can use in-memory TTL storage.

```mermaid
erDiagram
    SEARCH_QUERY ||--o{ DOUYIN_RESULT : returns
    DOUYIN_RESULT ||--o{ STREAM_HANDLE : resolves_to

    SEARCH_QUERY {
        string id
        string keyword
        string search_keyword
        string strategy_used
        datetime created_at
        int ttl_seconds
    }

    DOUYIN_RESULT {
        string result_id
        string query_id
        string douyin_aweme_id
        string title
        string description
        string author_name
        string author_id
        string cover_remote_url
        float duration
        int width
        int height
        json stats
        json raw
        datetime expires_at
    }

    STREAM_HANDLE {
        string id
        string result_id
        string remote_url
        json headers
        datetime resolved_at
        datetime expires_at
    }
```

## Search Query

Represents one search request.

- `id`: internal query ID.
- `keyword`: original user keyword.
- `search_keyword`: translated or final keyword sent to Douyin.
- `strategy_used`: `browser` or `direct_api`.
- `created_at`
- `ttl_seconds`

## Douyin Result

Normalized video result.

- `result_id`: module result ID.
- `douyin_aweme_id`: platform video ID.
- `title`
- `description`
- `author_name`
- `author_id`
- `cover_remote_url`
- `duration`
- `width`
- `height`
- `stats`
- `raw`: source-specific data kept for debugging and stream resolution.
- `expires_at`: result cache expiry.

## Stream Handle

Resolved playable video reference.

- `remote_url`: current Douyin media URL or play API URL.
- `headers`: request headers needed to fetch media.
- `resolved_at`
- `expires_at`

The frontend should never store or depend on `remote_url`. It should use:

```text
/api/douyin/results/{result_id}/stream
/api/douyin/results/{result_id}/download
```
