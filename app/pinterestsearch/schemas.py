from typing import Any, Literal

from pydantic import BaseModel, Field


PinterestMediaType = Literal["image", "video"]
PinterestMediaFilter = Literal["image", "video", "both"]
PinterestAspectFilter = Literal["9:16", "1:1", "16:9", "any"]


class ErrorPayload(BaseModel):
    code: str
    message: str
    retryable: bool = False


class SearchRequest(BaseModel):
    keyword: str = Field(..., min_length=1)
    limit: int = Field(default=24, ge=1, le=60)
    media_type: PinterestMediaFilter = "video"
    aspect_ratio: PinterestAspectFilter = "9:16"
    aspect_tolerance: float = Field(default=0.18, ge=0.02, le=0.75)


class PinterestResult(BaseModel):
    result_id: str = ""
    pin_id: str = ""
    title: str = ""
    description: str = ""
    media_type: PinterestMediaType = "image"
    media_remote_url: str = ""
    cover_remote_url: str = ""
    width: int = 0
    height: int = 0
    aspect_ratio: str = ""
    source_url: str = ""
    author_name: str = ""
    author_url: str = ""
    raw: dict[str, Any] = Field(default_factory=dict)


class PublicPinterestResult(BaseModel):
    result_id: str
    pin_id: str = ""
    title: str = ""
    description: str = ""
    media_type: PinterestMediaType
    media_url: str
    cover_url: str
    width: int = 0
    height: int = 0
    aspect_ratio: str = ""
    source_url: str = ""
    author_name: str = ""
    author_url: str = ""
    diagnostics: dict[str, Any] = Field(default_factory=dict)


class SearchResponse(BaseModel):
    success: bool = True
    keyword: str
    media_type: PinterestMediaFilter
    aspect_ratio: PinterestAspectFilter
    items: list[PublicPinterestResult]
    diagnostics: dict[str, Any] = Field(default_factory=dict)
