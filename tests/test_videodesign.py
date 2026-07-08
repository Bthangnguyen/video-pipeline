from fastapi.testclient import TestClient

from app.douyinsearch.schemas import DouyinResult, PublicDouyinResult, SearchResponse
from app.douyinsearch.service import douyin_service
from app.main import app
from app.pinterestsearch.schemas import PublicPinterestResult, SearchResponse as PinterestSearchResponse
from app.pinterestsearch.service import pinterest_service
from app.videodesign.planner import split_script
from app.videodesign.schemas import SplitSettings
from app.videodesign.service import videodesign_service


def _create_project(client: TestClient) -> str:
    response = client.post(
        "/api/videodesign/projects",
        json={
            "script": "Cats can recognize your voice. They often ignore it anyway. This makes cat videos funny.",
            "target_duration_seconds": 18,
            "language": "en",
        },
    )
    assert response.status_code == 200
    return response.json()["project"]["project_id"]


def test_videodesign_plans_dense_scenes():
    client = TestClient(app)
    project_id = _create_project(client)

    response = client.patch(
        f"/api/videodesign/projects/{project_id}/split-settings",
        json={"split_mode": "dense", "target_scene_duration_seconds": 3, "max_words_per_scene": 8},
    )
    assert response.status_code == 200

    response = client.post(f"/api/videodesign/projects/{project_id}/plan")

    assert response.status_code == 200
    scenes = response.json()["scenes"]
    assert len(scenes) >= 2
    assert scenes[0]["matching_keywords"]


def test_videodesign_split_uses_sentences_before_word_limit():
    script = "Tiny hook. A second short beat. This final sentence has enough words to still be one scene."

    scenes = split_script(script, SplitSettings(split_mode="normal", max_words_per_scene=18))

    assert [scene.voiceover_text for scene in scenes] == [
        "Tiny hook.",
        "A second short beat.",
        "This final sentence has enough words to still be one scene.",
    ]


def test_videodesign_split_breaks_only_overlong_sentence():
    script = "one two three four five six seven eight nine ten eleven twelve"

    scenes = split_script(script, SplitSettings(split_mode="normal", max_words_per_scene=5))

    assert len(scenes) == 3
    assert scenes[0].voiceover_text == "one two three four five"


def test_videodesign_tts_timing_only_generates_caption_chunks():
    client = TestClient(app)
    project_id = _create_project(client)
    client.post(f"/api/videodesign/projects/{project_id}/plan")

    response = client.post(
        f"/api/videodesign/projects/{project_id}/tts/generate",
        json={"provider": "timing_only", "voice_id": "test"},
    )

    assert response.status_code == 200
    scene = response.json()["scenes"][0]
    assert scene["tts"]["sync_state"] == "synced"
    assert scene["caption_chunks"]
    assert scene["duration_seconds"] > 0


def test_videodesign_get_and_update_project():
    client = TestClient(app)
    project_id = _create_project(client)

    update_response = client.patch(
        f"/api/videodesign/projects/{project_id}",
        json={"script": "A cleaner test script. It has two beats.", "style_brief": "clean social short"},
    )

    assert update_response.status_code == 200
    assert update_response.json()["project"]["script_source"] == "user"

    get_response = client.get(f"/api/videodesign/projects/{project_id}")

    assert get_response.status_code == 200
    project = get_response.json()["project"]
    assert project["script"] == "A cleaner test script. It has two beats."
    assert project["style_brief"] == "clean social short"


def test_videodesign_progress_endpoint_defaults_to_idle():
    client = TestClient(app)
    project_id = _create_project(client)

    response = client.get(f"/api/videodesign/projects/{project_id}/progress")

    assert response.status_code == 200
    progress = response.json()["progress"]
    assert progress["stage"] == "idle"
    assert progress["current"] == 0
    assert progress["total"] == 0


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

    async def fake_douyin_search(request):
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


def test_videodesign_smart_keywords_feed_material_search(monkeypatch):
    client = TestClient(app)
    project_id = _create_project(client)
    plan_response = client.post(f"/api/videodesign/projects/{project_id}/plan")
    scene_id = plan_response.json()["scenes"][0]["scene_id"]
    seen_keywords = []

    async def fake_keywords(**kwargs):
        return ["cat close up raw footage", "cat playing"]

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

    monkeypatch.setattr(videodesign_service.script_client, "generate_search_keywords", fake_keywords)
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
    assert seen_keywords == ["cat close up raw footage"]
    assert response.json()["rows"][0]["scene"]["matching_keywords"][0] == "cat close up raw footage"


def test_videodesign_review_download_and_timeline(monkeypatch):
    client = TestClient(app)
    project_id = _create_project(client)
    client.patch(
        f"/api/videodesign/projects/{project_id}/split-settings",
        json={"split_mode": "dense", "target_scene_duration_seconds": 3, "max_words_per_scene": 6},
    )
    plan_response = client.post(f"/api/videodesign/projects/{project_id}/plan")
    scene_id = plan_response.json()["scenes"][0]["scene_id"]

    douyin_service.store.put_many(
        [
            DouyinResult(
                result_id="vd-result",
                douyin_aweme_id="aweme-1",
                title="funny cat listening",
                stream_remote_url="https://example.test/play/video.mp4",
                raw={"video": {"play_addr": {"url_list": ["https://example.test/play/video.mp4"]}}},
            )
        ]
    )

    async def fake_search(request):
        return SearchResponse(
            keyword=request.keyword,
            search_keyword=request.keyword,
            strategy_used="browser",
            items=[
                PublicDouyinResult(
                    result_id="vd-result",
                    douyin_aweme_id="aweme-1",
                    title="funny cat listening",
                    cover_url="/cover",
                    stream_url="/stream",
                    download_url="/download",
                    duration=9.0,
                )
            ],
        )

    async def fake_download_to_file(result, output_path):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"video")
        return output_path

    monkeypatch.setattr(douyin_service, "search", fake_search)
    monkeypatch.setattr(douyin_service.stream_proxy, "download_to_file", fake_download_to_file)

    search_response = client.post(
        f"/api/videodesign/projects/{project_id}/materials/search",
        json={"scene_ids": [scene_id], "candidates_per_scene": 1, "queries_per_scene": 1},
    )
    assert search_response.status_code == 200
    candidate = search_response.json()["rows"][0]["candidates"][0]

    approve_response = client.patch(
        f"/api/videodesign/projects/{project_id}/scenes/{scene_id}/selection",
        json={"action": "approve", "candidate_id": candidate["candidate_id"]},
    )
    assert approve_response.status_code == 200
    assert approve_response.json()["scene"]["approval_state"] == "approved"

    download_response = client.post(
        f"/api/videodesign/projects/{project_id}/materials/download",
        json={"scene_ids": [scene_id]},
    )
    assert download_response.status_code == 200
    assert download_response.json()["assets"][0]["download_state"] == "downloaded"

    studio_response = client.post(f"/api/videodesign/projects/{project_id}/studio")
    assert studio_response.status_code == 400

    project = client.get(f"/api/videodesign/projects/{project_id}/review").json()
    for row in project["rows"][1:]:
        client.patch(
            f"/api/videodesign/projects/{project_id}/scenes/{row['scene']['scene_id']}/selection",
            json={"action": "placeholder"},
        )

    studio_response = client.post(f"/api/videodesign/projects/{project_id}/studio")
    assert studio_response.status_code == 200
    timeline = studio_response.json()["timeline"]
    assert timeline["items"][0]["source_ref"]["source"] == "material_asset"
    assert timeline["items"][0]["source_ref"]["media_url"].startswith(f"/api/videodesign/projects/{project_id}/materials/")
    assert timeline["items"][0]["source_ref"]["trim_start_seconds"] == 0.0
    assert timeline["items"][0]["source_ref"]["trim_end_seconds"] <= timeline["items"][0]["source_ref"]["timeline_duration_seconds"]
    assert timeline["items"][0]["source_ref"]["cut_strategy"] == "scene_duration_from_start"
    assert "overlay_default" in timeline["layers"]
    assert any(item["type"] == "overlay" for item in timeline["items"])

    text_item = next(item for item in timeline["items"] if item["type"] == "text")
    patch_response = client.patch(
        f"/api/videodesign/projects/{project_id}/timeline/items/{text_item['item_id']}",
        json={"source_ref": {"text": "Edited Studio text"}, "transform": {"x": 42, "y": 16}},
    )
    assert patch_response.status_code == 200
    assert patch_response.json()["item"]["source_ref"]["text"] == "Edited Studio text"
    assert patch_response.json()["item"]["transform"]["x"] == 42

    material_response = client.get(timeline["items"][0]["source_ref"]["media_url"])
    assert material_response.status_code == 200
    assert material_response.content == b"video"
