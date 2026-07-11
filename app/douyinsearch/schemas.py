from typing import Any, Literal

from pydantic import BaseModel, Field


SearchStrategy = Literal["auto", "browser", "direct_api"]


class ErrorPayload(BaseModel):
    code: str
    message: str
    retryable: bool = False


class SearchRequest(BaseModel):
    keyword: str = Field(..., min_length=1)
    translate_to_chinese: bool = True
    limit: int = Field(default=20, ge=1, le=50)
    cursor: str | None = None
    strategy: SearchStrategy = "auto"
    popular_first: bool = False


class DouyinResult(BaseModel):
    result_id: str
    douyin_aweme_id: str
    title: str = ""
    description: str = ""
    author_name: str = ""
    author_id: str = ""
    cover_remote_url: str = ""
    stream_remote_url: str = ""
    duration: float = 0
    width: int = 0
    height: int = 0
    stats: dict[str, Any] = Field(default_factory=dict)
    raw: dict[str, Any] = Field(default_factory=dict)


class PublicDouyinResult(BaseModel):
    result_id: str
    douyin_aweme_id: str
    title: str = ""
    description: str = ""
    author_name: str = ""
    author_id: str = ""
    cover_url: str
    stream_url: str
    download_url: str
    duration: float = 0
    width: int = 0
    height: int = 0
    stats: dict[str, Any] = Field(default_factory=dict)
    diagnostics: dict[str, Any] = Field(default_factory=dict)


class SearchResponse(BaseModel):
    success: bool = True
    keyword: str
    search_keyword: str
    strategy_used: str
    items: list[PublicDouyinResult]
    next_cursor: str | None = None
    diagnostics: dict[str, Any] = Field(default_factory=dict)
