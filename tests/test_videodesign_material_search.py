from pathlib import Path

from fastapi.testclient import TestClient

from app.douyinsearch.errors import DouyinSearchError
from app.douyinsearch.schemas import DouyinResult, PublicDouyinResult, SearchResponse
from app.douyinsearch.service import douyin_service
from app.main import app
from app.pinterestsearch.errors import PinterestSearchError
from app.pinterestsearch.schemas import PublicPinterestResult, SearchResponse as PinterestSearchResponse
from app.pinterestsearch.service import pinterest_service
from app.videodesign.audio import measure_audio_duration
from app.videodesign.errors import DOWNLOAD_FAILED, SCRIPT_GENERATION_FAILED, VideoDesignError
from app.videodesign.planner import split_script
from app.videodesign.schemas import MaterialAsset, MediaCandidate, SmoothPreview, SplitSettings
import app.videodesign.service as videodesign_service_module
from app.videodesign.service import _download_source_url, videodesign_service
from tests.videodesign_helpers import create_project as _create_project, write_test_wav as _write_test_wav


def test_videodesign_search_single_scene_endpoint(monkeypatch):
    client = TestClient(app)
    project_id = _create_project(client)
    plan_response = client.post(f"/api/videodesign/projects/{project_id}/plan")
    scene_id = plan_response.json()["scenes"][0]["scene_id"]

    async def fake_search(request):
        return SearchResponse(
            keyword=request.keyword,
            search_keyword=request.keyword,
            strategy_used="browser",
            items=[
                PublicDouyinResult(
                    result_id="single-scene-result",
                    douyin_aweme_id="aweme-single",
                    title="cat voice test",
                    cover_url="/cover",
                    stream_url="/stream",
                    download_url="/download",
                    duration=5.0,
                )
            ],
        )

    monkeypatch.setattr(douyin_service, "search", fake_search)

    response = client.post(
        f"/api/videodesign/projects/{project_id}/scenes/{scene_id}/materials/search",
        json={"candidates_per_scene": 1, "queries_per_scene": 1},
    )

    assert response.status_code == 200
    rows = response.json()["rows"]
    selected = next(row for row in rows if row["scene"]["scene_id"] == scene_id)
    assert selected["candidates"][0]["douyin_aweme_id"] == "aweme-single"


def test_videodesign_search_returns_douyin_and_pinterest_candidates(monkeypatch):
    client = TestClient(app)
    project_id = _create_project(client)
    plan_response = client.post(f"/api/videodesign/projects/{project_id}/plan")
    scene_id = plan_response.json()["scenes"][0]["scene_id"]
    client.patch(
        f"/api/videodesign/projects/{project_id}/scenes/{scene_id}",
        json={
            "visual_search_plan": {
                "douyin_primary_keyword": "情侣 冷战",
                "pinterest_primary_keyword": "couple awkward silence vertical video",
                "fallbacks": {"douyin": [], "pinterest": []},
            },
            "matching_keywords": ["couple awkward silence vertical video"],
        },
    )
    seen = {"douyin": [], "pinterest": []}

    async def fake_douyin_search(request):
        seen["douyin"].append((request.keyword, request.translate_to_chinese))
        return SearchResponse(
            keyword=request.keyword,
            search_keyword=request.keyword,
            strategy_used="browser",
            items=[
                PublicDouyinResult(
                    result_id="dy-result",
                    douyin_aweme_id="dy-aweme",
                    title="cat raw footage",
                    cover_url="/dy-cover",
                    stream_url="/dy-stream",
                    download_url="/dy-download",
                    duration=5.0,
                )
            ],
        )

    async def fake_pinterest_search(request):
        seen["pinterest"].append(request.keyword)
        return PinterestSearchResponse(
            keyword=request.keyword,
            media_type="video",
            aspect_ratio="9:16",
            items=[
                PublicPinterestResult(
                    result_id="pin-result",
                    pin_id="pin-1",
                    title="cat vertical video",
                    media_type="video",
                    media_url="/pin-media",
                    stream_url="/pin-stream",
                    download_url="/pin-download",
                    cover_url="/pin-cover",
                    width=576,
                    height=1024,
                    aspect_ratio="9:16",
                )
            ],
        )

    monkeypatch.setattr(douyin_service, "search", fake_douyin_search)
    monkeypatch.setattr(pinterest_service, "search", fake_pinterest_search)

    response = client.post(
        f"/api/videodesign/projects/{project_id}/materials/search",
        json={
            "scene_ids": [scene_id],
            "douyin_min_per_scene": 1,
            "pinterest_min_per_scene": 1,
            "queries_per_scene": 1,
        },
    )

    assert response.status_code == 200
    candidates = response.json()["rows"][0]["candidates"]
    assert {candidate["source"] for candidate in candidates} == {"douyinsearch", "pinterestsearch"}
    assert {candidate["source_item_id"] for candidate in candidates} == {"dy-aweme", "pin-1"}
    pinterest_candidate = next(candidate for candidate in candidates if candidate["source"] == "pinterestsearch")
    assert pinterest_candidate["media_url"] == "/pin-media"
    assert seen["douyin"] == [("情侣 冷战", False)]
    assert seen["pinterest"] == ["couple awkward silence vertical video"]


def test_videodesign_materials_preflight_returns_source_checks(monkeypatch):
    client = TestClient(app)

    async def fake_douyin_preflight(keyword):
        return {
            "success": True,
            "source": "douyinsearch",
            "state": "valid",
            "checks": [{"name": "load_jingxuan", "ok": True, "message": keyword, "detail": {}}],
        }

    async def fake_pinterest_preflight(keyword):
        return {
            "success": False,
            "source": "pinterestsearch",
            "state": "challenge_required",
            "checks": [{"name": "anti_bot", "ok": False, "message": "challenge", "detail": {}}],
        }

    monkeypatch.setattr(douyin_service, "preflight_check", fake_douyin_preflight)
    monkeypatch.setattr(pinterest_service, "preflight_check", fake_pinterest_preflight)

    response = client.post("/api/videodesign/materials/preflight", json={"keyword": "cat"})

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["healthy"] is False
    assert [source["source"] for source in body["sources"]] == ["douyinsearch", "pinterestsearch"]
    assert body["sources"][0]["checks"][0]["name"] == "load_jingxuan"


def test_videodesign_material_search_keeps_partial_results_when_source_fails(monkeypatch):
    client = TestClient(app)
    project_id = _create_project(client)
    plan_response = client.post(f"/api/videodesign/projects/{project_id}/plan")
    scene_id = plan_response.json()["scenes"][0]["scene_id"]

    async def fake_douyin_search(request):
        return SearchResponse(
            keyword=request.keyword,
            search_keyword=request.keyword,
            strategy_used="browser",
            items=[
                PublicDouyinResult(
                    result_id="partial-dy-result",
                    douyin_aweme_id="partial-dy",
                    title="cat raw footage",
                    cover_url="/dy-cover",
                    stream_url="/dy-stream",
                    download_url="/dy-download",
                    duration=5.0,
                )
            ],
        )

    async def fake_pinterest_search(request):
        raise PinterestSearchError("NETWORK_ERROR", "Pinterest network is unavailable.", retryable=True)

    monkeypatch.setattr(douyin_service, "search", fake_douyin_search)
    monkeypatch.setattr(pinterest_service, "search", fake_pinterest_search)

    response = client.post(
        f"/api/videodesign/projects/{project_id}/materials/search",
        json={
            "scene_ids": [scene_id],
            "douyin_min_per_scene": 1,
            "pinterest_min_per_scene": 1,
            "queries_per_scene": 1,
        },
    )

    assert response.status_code == 200
    candidates = response.json()["rows"][0]["candidates"]
    assert [candidate["source"] for candidate in candidates] == ["douyinsearch"]

    review_response = client.get(f"/api/videodesign/projects/{project_id}/review")
    assert review_response.status_code == 200
    assert review_response.json()["rows"][0]["candidates"][0]["source_item_id"] == "partial-dy"
    assert review_response.json()["rows"][0]["search_errors"][0]["source"] == "pinterestsearch"
    assert review_response.json()["rows"][0]["search_errors"][0]["keyword"]


def test_videodesign_material_search_clears_old_scene_errors(monkeypatch):
    client = TestClient(app)
    project_id = _create_project(client)
    plan_response = client.post(f"/api/videodesign/projects/{project_id}/plan")
    scene_id = plan_response.json()["scenes"][0]["scene_id"]

    async def failing_search(request):
        raise DouyinSearchError("NO_RESULTS", "No old results.", retryable=True)

    monkeypatch.setattr(douyin_service, "search", failing_search)
    first_response = client.post(
        f"/api/videodesign/projects/{project_id}/materials/search",
        json={"scene_ids": [scene_id], "douyin_min_per_scene": 1, "pinterest_min_per_scene": 0, "queries_per_scene": 1},
    )
    assert first_response.status_code == 200
    assert first_response.json()["rows"][0]["search_errors"][0]["code"] == "NO_RESULTS"

    async def successful_search(request):
        return SearchResponse(
            keyword=request.keyword,
            search_keyword=request.keyword,
            strategy_used="browser",
            items=[
                PublicDouyinResult(
                    result_id="fresh-result",
                    douyin_aweme_id="fresh-aweme",
                    title="fresh cat footage",
                    cover_url="/cover",
                    stream_url="/stream",
                    download_url="/download",
                    duration=5.0,
                )
            ],
        )

    monkeypatch.setattr(douyin_service, "search", successful_search)
    second_response = client.post(
        f"/api/videodesign/projects/{project_id}/materials/search",
        json={"scene_ids": [scene_id], "douyin_min_per_scene": 1, "pinterest_min_per_scene": 0, "queries_per_scene": 1},
    )
    assert second_response.status_code == 200
    row = second_response.json()["rows"][0]
    assert row["candidates"][0]["source_item_id"] == "fresh-aweme"
    assert row["search_errors"] == []


def test_videodesign_material_search_tries_next_keyword_after_failure(monkeypatch):
    client = TestClient(app)
    project_id = _create_project(client)
    plan_response = client.post(f"/api/videodesign/projects/{project_id}/plan")
    scene_id = plan_response.json()["scenes"][0]["scene_id"]
    client.patch(
        f"/api/videodesign/projects/{project_id}/scenes/{scene_id}",
        json={"matching_keywords": ["bad keyword", "cat raw footage"]},
    )
    seen_keywords = []

    async def fake_search(request):
        seen_keywords.append(request.keyword)
        if request.keyword == "bad keyword":
            raise DouyinSearchError("NO_RESULTS", "No results.", retryable=True)
        return SearchResponse(
            keyword=request.keyword,
            search_keyword=request.keyword,
            strategy_used="browser",
            items=[
                PublicDouyinResult(
                    result_id="next-keyword-result",
                    douyin_aweme_id="next-keyword-aweme",
                    title="cat raw footage",
                    cover_url="/cover",
                    stream_url="/stream",
                    download_url="/download",
                    duration=5.0,
                )
            ],
        )

    monkeypatch.setattr(douyin_service, "search", fake_search)

    response = client.post(
        f"/api/videodesign/projects/{project_id}/materials/search",
        json={
            "scene_ids": [scene_id],
            "douyin_min_per_scene": 1,
            "pinterest_min_per_scene": 0,
            "queries_per_scene": 2,
        },
    )

    assert response.status_code == 200
    assert seen_keywords == ["bad keyword", "cat raw footage"]
    assert response.json()["rows"][0]["candidates"][0]["search_keyword"] == "cat raw footage"


def test_videodesign_smart_keywords_feed_material_search(monkeypatch):
    client = TestClient(app)
    project_id = _create_project(client)
    plan_response = client.post(f"/api/videodesign/projects/{project_id}/plan")
    scene_id = plan_response.json()["scenes"][0]["scene_id"]
    seen_keywords = []
    visual_calls = []

    async def fake_visual_keywords(**kwargs):
        visual_calls.append(kwargs["scenes"])
        input_scene = kwargs["scenes"][0]
        return {
            "project_anchor": "cat",
            "scenes": [
                {
                    "scene_id": input_scene["scene_id"],
                    "retention_role": "hook",
                    "content_anchor": "cat",
                    "visible_action": "reacting",
                    "visual_intent": "cat reacting to a voice",
                    "visual_archetype": "cat close up",
                    "douyin_primary_keyword": "猫咪 反应",
                    "pinterest_primary_keyword": "cat reacting video",
                    "fallbacks": {"douyin": ["猫咪 日常"], "pinterest": ["cat reacting video"]},
                    "avoid": [],
                    "material_notes": "Prefer real cat footage.",
                }
            ]
        }

    async def fake_search(request):
        seen_keywords.append(request.keyword)
        return SearchResponse(
            keyword=request.keyword,
            search_keyword=request.keyword,
            strategy_used="browser",
            items=[
                PublicDouyinResult(
                    result_id="smart-dy-result",
                    douyin_aweme_id="smart-dy",
                    title="clean cat close up",
                    cover_url="/cover",
                    stream_url="/stream",
                    download_url="/download",
                    duration=5.0,
                )
            ],
        )

    async def fake_pinterest_search(request):
        return PinterestSearchResponse(
            keyword=request.keyword,
            media_type="video",
            aspect_ratio="9:16",
            items=[
                PublicPinterestResult(
                    result_id="smart-pin-result",
                    pin_id="smart-pin",
                    title="cat reacting",
                    media_type="video",
                    media_url="/pin-media",
                    stream_url="/pin-stream",
                    download_url="/pin-download",
                    cover_url="/pin-cover",
                    width=576,
                    height=1024,
                    aspect_ratio="9:16",
                )
            ],
        )

    monkeypatch.setattr(videodesign_service.script_client, "generate_visual_search_keywords", fake_visual_keywords)
    monkeypatch.setattr(douyin_service, "search", fake_search)
    monkeypatch.setattr(pinterest_service, "search", fake_pinterest_search)

    response = client.post(
        f"/api/videodesign/projects/{project_id}/materials/search",
        json={
            "scene_ids": [scene_id],
            "douyin_min_per_scene": 1,
            "pinterest_min_per_scene": 1,
            "queries_per_scene": 1,
            "use_smart_keywords": True,
        },
    )

    assert response.status_code == 200
    assert len(visual_calls) == 1
    assert seen_keywords == ["猫咪 反应"]
    scene = response.json()["rows"][0]["scene"]
    assert scene["matching_keywords"][0] == "cat reacting video"
    assert scene["visual_search_plan"]["douyin_primary_keyword"] == "猫咪 反应"
