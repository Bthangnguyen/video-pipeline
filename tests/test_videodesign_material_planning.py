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


def test_videodesign_keyword_generation_endpoint_updates_scene(monkeypatch):
    client = TestClient(app)
    project_id = _create_project(client)
    plan_response = client.post(f"/api/videodesign/projects/{project_id}/plan")
    scene_id = plan_response.json()["scenes"][0]["scene_id"]

    async def fake_visual_keywords(**kwargs):
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

    monkeypatch.setattr(videodesign_service.script_client, "generate_visual_search_keywords", fake_visual_keywords)

    response = client.post(
        f"/api/videodesign/projects/{project_id}/keywords/generate",
        json={"scene_ids": [scene_id]},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["errors"] == []
    assert body["scenes"][0]["matching_keywords"] == ["cat reacting video"]
    assert body["scenes"][0]["visual_search_plan"]["douyin_primary_keyword"] == "猫咪 反应"


def test_videodesign_keyword_generation_plans_all_scenes_in_one_call(monkeypatch):
    client = TestClient(app)
    project_id = _create_project(client)
    scenes = client.post(f"/api/videodesign/projects/{project_id}/plan").json()["scenes"]
    calls = []

    async def fake_visual_keywords(**kwargs):
        calls.append(kwargs["scenes"])
        return {
            "project_anchor": "cat",
            "scenes": [
                {
                    "scene_id": item["scene_id"],
                    "retention_role": "hook" if item["order"] == 1 else "evidence",
                    "content_anchor": "cat",
                    "visible_action": "playing",
                    "visual_intent": "real cat behavior",
                    "visual_archetype": "cat behavior",
                    "douyin_primary_keyword": "猫咪 日常",
                    "pinterest_primary_keyword": "cat playing video",
                    "fallbacks": {"douyin": [], "pinterest": []},
                    "avoid": [],
                    "material_notes": "Prefer ordinary cat footage.",
                }
                for item in kwargs["scenes"]
            ],
        }

    monkeypatch.setattr(videodesign_service.script_client, "generate_visual_search_keywords", fake_visual_keywords)

    response = client.post(
        f"/api/videodesign/projects/{project_id}/keywords/generate",
        json={"scene_ids": None},
    )

    assert response.status_code == 200
    assert len(calls) == 1
    assert {item["scene_id"] for item in calls[0]} == {scene["scene_id"] for scene in scenes}
    assert response.json()["errors"] == []
    assert all(scene["visual_search_plan"]["query_strategy"] == "broad_grounded_v2" for scene in response.json()["scenes"])


def test_videodesign_keyword_generation_creates_shared_v3_groups(monkeypatch):
    client = TestClient(app)
    project_id = _create_project(client)
    scenes = client.post(f"/api/videodesign/projects/{project_id}/plan").json()["scenes"]

    async def fake_visual_keywords(**kwargs):
        scene_ids = [scene["scene_id"] for scene in kwargs["scenes"]]
        return {
            "project_anchor": "cats",
            "groups": [
                {
                    "role": "hook",
                    "label": "Cute cats",
                    "douyin_keyword": "可爱猫咪",
                    "pinterest_keyword": "cute cats",
                    "scene_ids": scene_ids[:1],
                },
                {
                    "role": "base",
                    "label": "Cats",
                    "douyin_keyword": "猫咪日常",
                    "pinterest_keyword": "cats",
                    "scene_ids": scene_ids[1:],
                },
            ],
        }

    monkeypatch.setattr(videodesign_service.script_client, "generate_visual_search_keywords", fake_visual_keywords)

    response = client.post(
        f"/api/videodesign/projects/{project_id}/keywords/generate",
        json={"scene_ids": None},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["errors"] == []
    assert {group["role"] for group in body["search_plan"]["groups"]} == {"hook", "base"}
    assert all(scene["search_group_id"] for scene in body["scenes"])
    assert all(scene["visual_search_plan"]["query_strategy"] == "shared_pool_v3" for scene in body["scenes"])


def test_videodesign_shared_group_searches_douyin_once_for_all_scenes(monkeypatch):
    client = TestClient(app)
    project_id = _create_project(client)
    scenes = client.post(f"/api/videodesign/projects/{project_id}/plan").json()["scenes"]
    scene_ids = [scene["scene_id"] for scene in scenes]
    patch_response = client.patch(
        f"/api/videodesign/projects/{project_id}/search-plan",
        json={
            "popular_first": True,
            "groups": [
                {
                    "group_id": "grp_cats",
                    "role": "base",
                    "label": "Cats",
                    "douyin_keyword": "猫咪日常",
                    "pinterest_keyword": "cats",
                    "scene_ids": scene_ids,
                }
            ],
        },
    )
    assert patch_response.status_code == 200
    calls = []

    async def fake_search(request):
        calls.append(request)
        return SearchResponse(
            keyword=request.keyword,
            search_keyword=request.keyword,
            strategy_used="browser",
            diagnostics={
                "popularity": {
                    "requested": True,
                    "applied": True,
                    "method": "browser_filter",
                    "publish_window_days": 180,
                }
            },
            items=[
                PublicDouyinResult(
                    result_id="shared-result",
                    douyin_aweme_id="shared-aweme",
                    title="popular cat",
                    cover_url="/cover",
                    stream_url="/stream",
                    download_url="/download",
                    duration=5.0,
                    stats={"digg_count": 1234},
                )
            ],
        )

    monkeypatch.setattr(douyin_service, "search", fake_search)

    response = client.post(
        f"/api/videodesign/projects/{project_id}/materials/search",
        json={
            "group_ids": ["grp_cats"],
            "douyin_min_per_scene": 1,
            "pinterest_min_per_scene": 0,
            "popular_first": True,
        },
    )

    assert response.status_code == 200
    assert len(calls) == 1
    assert calls[0].keyword == "猫咪日常"
    assert calls[0].popular_first is True
    rows = response.json()["rows"]
    assert all(len(row["candidates"]) == 1 for row in rows)
    assert all(row["candidates"][0]["search_group_id"] == "grp_cats" for row in rows)
    assert all(row["candidates"][0]["stats"]["digg_count"] == 1234 for row in rows)
    assert all(row["candidates"][0]["popularity"]["applied"] is True for row in rows)


def test_videodesign_popular_first_can_be_disabled(monkeypatch):
    client = TestClient(app)
    project_id = _create_project(client)
    scenes = client.post(f"/api/videodesign/projects/{project_id}/plan").json()["scenes"]
    scene_ids = [scene["scene_id"] for scene in scenes]
    client.patch(
        f"/api/videodesign/projects/{project_id}/search-plan",
        json={
            "popular_first": True,
            "groups": [
                {
                    "group_id": "grp_cats",
                    "role": "base",
                    "label": "Cats",
                    "douyin_keyword": "猫咪",
                    "pinterest_keyword": "cats",
                    "scene_ids": scene_ids,
                }
            ],
        },
    )
    seen = []

    async def fake_search(request):
        seen.append(request.popular_first)
        return SearchResponse(
            keyword=request.keyword,
            search_keyword=request.keyword,
            strategy_used="browser",
            items=[
                PublicDouyinResult(
                    result_id="relevance-result",
                    douyin_aweme_id="relevance-aweme",
                    cover_url="/cover",
                    stream_url="/stream",
                    download_url="/download",
                )
            ],
        )

    monkeypatch.setattr(douyin_service, "search", fake_search)
    response = client.post(
        f"/api/videodesign/projects/{project_id}/materials/search",
        json={
            "group_ids": ["grp_cats"],
            "douyin_min_per_scene": 1,
            "pinterest_min_per_scene": 0,
            "popular_first": False,
        },
    )

    assert response.status_code == 200
    assert seen == [False]
    assert response.json()["search_plan"]["popular_first"] is False


def test_videodesign_keyword_generation_rejects_off_topic_story(monkeypatch):
    client = TestClient(app)
    create_response = client.post(
        "/api/videodesign/projects",
        json={
            "idea": "japan family",
            "script": "In Japan, taking off shoes at the genkan keeps street dirt outside. Tatami floors stay cleaner.",
            "target_duration_seconds": 18,
            "language": "en",
        },
    )
    project_id = create_response.json()["project"]["project_id"]
    scenes = client.post(f"/api/videodesign/projects/{project_id}/plan").json()["scenes"]

    async def fake_visual_keywords(**kwargs):
        return {
            "project_anchor": "Japanese home",
            "scenes": [
                {
                    "scene_id": item["scene_id"],
                    "retention_role": "evidence",
                    "content_anchor": "couple",
                    "visible_action": "sitting apart",
                    "visual_intent": "relationship tension",
                    "visual_archetype": "couple conflict",
                    "douyin_primary_keyword": "日本夫妻 冷战 沙发",
                    "pinterest_primary_keyword": "Japanese couple sitting apart sofa vertical video",
                    "fallbacks": {"douyin": [], "pinterest": []},
                    "avoid": [],
                    "material_notes": "",
                }
                for item in kwargs["scenes"]
            ],
        }

    monkeypatch.setattr(videodesign_service.script_client, "generate_visual_search_keywords", fake_visual_keywords)

    response = client.post(
        f"/api/videodesign/projects/{project_id}/keywords/generate",
        json={"scene_ids": None},
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body["errors"]) == len(scenes)
    assert all(scene["visual_search_plan"]["query_strategy"] == "fallback_ungrounded" for scene in body["scenes"])
    assert all("couple" not in scene["visual_search_plan"]["pinterest_primary_keyword"].lower() for scene in body["scenes"])


def test_videodesign_visual_queries_remove_niche_style_terms_and_japanese_spellings():
    assert videodesign_service_module._normalize_pinterest_visual_query(
        "cat cinematic close up vertical video"
    ) == "cat video"
    assert videodesign_service_module._normalize_douyin_visual_query("玄関 実写 靴下") == "玄关 实拍 袜子"
    assert videodesign_service_module._normalize_douyin_visual_query("家族 団らん 実写") == ""


def test_videodesign_smart_keyword_failure_falls_back_during_search(monkeypatch):
    client = TestClient(app)
    project_id = _create_project(client)
    plan_response = client.post(f"/api/videodesign/projects/{project_id}/plan")
    scene_id = plan_response.json()["scenes"][0]["scene_id"]
    seen_keywords = []

    async def fake_visual_keywords(**kwargs):
        raise VideoDesignError(SCRIPT_GENERATION_FAILED, "DeepSeek keyword generation failed: network", retryable=True)

    async def fake_search(request):
        seen_keywords.append(request.keyword)
        return SearchResponse(
            keyword=request.keyword,
            search_keyword=request.keyword,
            strategy_used="browser",
            items=[
                PublicDouyinResult(
                    result_id="fallback-dy-result",
                    douyin_aweme_id="fallback-dy",
                    title="cat voice raw footage",
                    cover_url="/cover",
                    stream_url="/stream",
                    download_url="/download",
                    duration=5.0,
                )
            ],
        )

    monkeypatch.setattr(videodesign_service.script_client, "generate_visual_search_keywords", fake_visual_keywords)
    monkeypatch.setattr(douyin_service, "search", fake_search)

    response = client.post(
        f"/api/videodesign/projects/{project_id}/materials/search",
        json={
            "scene_ids": [scene_id],
            "douyin_min_per_scene": 1,
            "pinterest_min_per_scene": 0,
            "queries_per_scene": 1,
            "use_smart_keywords": True,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["rows"][0]["candidates"]
    assert seen_keywords == [body["rows"][0]["scene"]["matching_keywords"][0]]
