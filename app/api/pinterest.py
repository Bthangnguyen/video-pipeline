from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.pinterestsearch.errors import PinterestSearchError
from app.pinterestsearch.schemas import SearchRequest
from app.pinterestsearch.service import pinterest_service

router = APIRouter()


def error_response(error: PinterestSearchError):
    status_code = 404 if error.code == "RESULT_EXPIRED" else 400
    return JSONResponse(
        status_code=status_code,
        content={"success": False, "error": error.to_payload()},
    )


@router.get("/health")
async def health():
    return pinterest_service.health()


@router.post("/session/check")
async def session_check():
    return await pinterest_service.check_session()


@router.post("/search")
async def search(request: SearchRequest):
    try:
        return await pinterest_service.search(request)
    except PinterestSearchError as error:
        return error_response(error)


@router.get("/results/{result_id}")
async def get_result(result_id: str):
    try:
        return pinterest_service.get_result(result_id)
    except PinterestSearchError as error:
        return error_response(error)


@router.get("/results/{result_id}/cover")
async def cover(result_id: str):
    try:
        return await pinterest_service.proxy_cover(result_id)
    except PinterestSearchError as error:
        return error_response(error)


@router.get("/results/{result_id}/media")
async def media(result_id: str, request: Request):
    try:
        return await pinterest_service.proxy_media(result_id, request.headers.get("range"))
    except PinterestSearchError as error:
        return error_response(error)
