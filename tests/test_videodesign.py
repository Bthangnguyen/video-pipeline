from fastapi.testclient import TestClient

from app.douyinsearch.errors import DouyinSearchError
from app.douyinsearch.schemas import DouyinResult, PublicDouyinResult, SearchResponse
from app.douyinsearch.service import douyin_service
from app.main import app
from app.pinterestsearch.errors import PinterestSearchError
from app.pinterestsearch.schemas import PublicPinterestResult, SearchResponse as PinterestSearchResponse
from app.pinterestsearch.service import pinterest_service
from app.videodesign.errors import SCRIPT_GENERATION_FAILED, VideoDesignError
from app.videodesign.planner import split_script
from app.videodesign.schemas import MaterialAsset, MediaCandidate, SplitSettings
from app.videodesign.service import _download_source_url, videodesign_service


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
    pinterest_candidate = next(candidate for candidate in candidates if candidate["source"] == "pinterestsearch")
    assert pinterest_candidate["media_url"] == "/pin-media"


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


def test_videodesign_keyword_generation_endpoint_updates_scene(monkeypatch):
    client = TestClient(app)
    project_id = _create_project(client)
    plan_response = client.post(f"/api/videodesign/projects/{project_id}/plan")
    scene_id = plan_response.json()["scenes"][0]["scene_id"]

    async def fake_keywords(**kwargs):
        return ["cat close up raw footage", "cat playing"]

    monkeypatch.setattr(videodesign_service.script_client, "generate_search_keywords", fake_keywords)

    response = client.post(
        f"/api/videodesign/projects/{project_id}/keywords/generate",
        json={"scene_ids": [scene_id]},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["errors"] == []
    assert body["scenes"][0]["matching_keywords"] == ["cat close up raw footage", "cat playing"]


def test_videodesign_smart_keyword_failure_falls_back_during_search(monkeypatch):
    client = TestClient(app)
    project_id = _create_project(client)
    plan_response = client.post(f"/api/videodesign/projects/{project_id}/plan")
    scene_id = plan_response.json()["scenes"][0]["scene_id"]
    seen_keywords = []

    async def fake_keywords(**kwargs):
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
    body = response.json()
    assert body["rows"][0]["candidates"]
    assert seen_keywords == [body["rows"][0]["scene"]["matching_keywords"][0]]


def test_videodesign_downloads_pinterest_candidate_with_ytdlp(monkeypatch, tmp_path):
    client = TestClient(app)
    project_id = _create_project(client)
    plan_response = client.post(f"/api/videodesign/projects/{project_id}/plan")
    scene_id = plan_response.json()["scenes"][0]["scene_id"]
    calls = []

    async def fake_pinterest_search(request):
        return PinterestSearchResponse(
            keyword=request.keyword,
            media_type="video",
            aspect_ratio="9:16",
            items=[
                PublicPinterestResult(
                    result_id="pin-ytdlp-result",
                    pin_id="123",
                    title="cat video",
                    media_type="video",
                    media_url="/pin-media",
                    stream_url="/pin-stream",
                    download_url="/pin-download",
                    cover_url="/pin-cover",
                    source_url="https://www.pinterest.com/pin/123/",
                )
            ],
        )

    async def fake_ytdlp_download(url, output_path, cookie_file=None, cookie_header=""):
        calls.append((url, cookie_file, cookie_header))
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"video")
        return output_path

    monkeypatch.setattr(pinterest_service, "search", fake_pinterest_search)
    monkeypatch.setattr(videodesign_service.ytdlp, "download", fake_ytdlp_download)

    search_response = client.post(
        f"/api/videodesign/projects/{project_id}/materials/search",
        json={
            "scene_ids": [scene_id],
            "douyin_min_per_scene": 0,
            "pinterest_min_per_scene": 1,
            "queries_per_scene": 1,
        },
    )
    candidate = search_response.json()["rows"][0]["candidates"][0]
    client.patch(
        f"/api/videodesign/projects/{project_id}/scenes/{scene_id}/selection",
        json={"action": "approve", "candidate_id": candidate["candidate_id"]},
    )

    download_response = client.post(
        f"/api/videodesign/projects/{project_id}/materials/download",
        json={"scene_ids": [scene_id], "force": True},
    )

    assert download_response.status_code == 200
    assert calls[0][0] == "https://www.pinterest.com/pin/123/"
    assert download_response.json()["assets"][0]["source_url"] == "https://www.pinterest.com/pin/123/"


def test_videodesign_downloads_douyin_candidate_after_result_cache_expires(monkeypatch, tmp_path):
    client = TestClient(app)
    project_id = _create_project(client)
    plan_response = client.post(f"/api/videodesign/projects/{project_id}/plan")
    scene_id = plan_response.json()["scenes"][0]["scene_id"]

    candidate = MediaCandidate(
        candidate_id="cand-dy-remote",
        source="douyinsearch",
        scene_id=scene_id,
        source_result_id="expired-result",
        source_item_id="7502421161918696761",
        douyin_result_id="expired-result",
        douyin_aweme_id="7502421161918696761",
        source_url="https://www.douyin.com/video/7502421161918696761",
        remote_download_url="https://example.com/douyin.mp4",
        status="approved",
    )
    project = videodesign_service.store.get(project_id)
    scene = next(item for item in project.scenes if item.scene_id == scene_id)
    project.candidates.append(candidate)
    scene.selected_candidate_id = candidate.candidate_id
    scene.approval_state = "approved"
    videodesign_service.store.put(project)

    async def fake_ytdlp_fail(*args, **kwargs):
        raise RuntimeError("yt-dlp needs fresh cookies")

    async def fake_download_url(remote_url, output_path):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"video")
        assert remote_url == "https://example.com/douyin.mp4"
        return output_path

    monkeypatch.setattr(videodesign_service.ytdlp, "download", fake_ytdlp_fail)
    monkeypatch.setattr(douyin_service.stream_proxy, "download_url_to_file", fake_download_url)
    monkeypatch.setattr(douyin_service.store, "get", lambda result_id: None)

    response = client.post(
        f"/api/videodesign/projects/{project_id}/materials/download",
        json={"scene_ids": [scene_id]},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["assets"][0]["candidate_id"] == "cand-dy-remote"
    assert body["skipped"] == []


def test_videodesign_download_skips_unapproved_scene(monkeypatch):
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
                    result_id="unapproved-result",
                    douyin_aweme_id="unapproved-aweme",
                    title="cat footage",
                    cover_url="/cover",
                    stream_url="/stream",
                    download_url="/download",
                    duration=5.0,
                )
            ],
        )

    monkeypatch.setattr(douyin_service, "search", fake_search)
    search_response = client.post(
        f"/api/videodesign/projects/{project_id}/materials/search",
        json={"scene_ids": [scene_id], "douyin_min_per_scene": 1, "pinterest_min_per_scene": 0, "queries_per_scene": 1},
    )
    assert search_response.status_code == 200

    project = videodesign_service.store.get(project_id)
    scene = next(item for item in project.scenes if item.scene_id == scene_id)
    scene.selected_candidate_id = search_response.json()["rows"][0]["candidates"][0]["candidate_id"]
    videodesign_service.store.put(project)

    download_response = client.post(
        f"/api/videodesign/projects/{project_id}/materials/download",
        json={"scene_ids": [scene_id]},
    )

    assert download_response.status_code == 200
    body = download_response.json()
    assert body["assets"] == []
    assert body["skipped"][0]["scene_id"] == scene_id


def test_videodesign_prune_keeps_only_selected_candidate(monkeypatch):
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
                    result_id="keep-dy",
                    douyin_aweme_id="keep-aweme",
                    title="cat close up",
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
                    result_id="remove-pin",
                    pin_id="remove-pin-id",
                    title="extra cat video",
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
    search_response = client.post(
        f"/api/videodesign/projects/{project_id}/materials/search",
        json={"scene_ids": [scene_id], "douyin_min_per_scene": 1, "pinterest_min_per_scene": 1, "queries_per_scene": 1},
    )
    candidates = search_response.json()["rows"][0]["candidates"]
    selected = next(candidate for candidate in candidates if candidate["source"] == "douyinsearch")
    client.patch(
        f"/api/videodesign/projects/{project_id}/scenes/{scene_id}/selection",
        json={"action": "approve", "candidate_id": selected["candidate_id"]},
    )

    prune_response = client.post(
        f"/api/videodesign/projects/{project_id}/materials/prune",
        json={"scene_ids": [scene_id]},
    )

    assert prune_response.status_code == 200
    assert prune_response.json()["removed"] == 1
    review = client.get(f"/api/videodesign/projects/{project_id}/review").json()
    assert [candidate["candidate_id"] for candidate in review["rows"][0]["candidates"]] == [selected["candidate_id"]]


def test_videodesign_derives_download_urls_for_old_candidates():
    assert (
        _download_source_url(
            MediaCandidate(
                candidate_id="cand-old-pin",
                source="pinterestsearch",
                scene_id="scene",
                source_item_id="123",
            )
        )
        == "https://www.pinterest.com/pin/123/"
    )
    assert (
        _download_source_url(
            MediaCandidate(
                candidate_id="cand-old-dy",
                source="douyinsearch",
                scene_id="scene",
                douyin_aweme_id="456",
            )
        )
        == "https://www.douyin.com/video/456"
    )


def test_videodesign_review_download_and_timeline(monkeypatch):
    client = TestClient(app)
    project_id = _create_project(client)
    client.patch(
        f"/api/videodesign/projects/{project_id}/split-settings",
        json={"split_mode": "dense", "target_scene_duration_seconds": 3, "max_words_per_scene": 6},
    )
    plan_response = client.post(f"/api/videodesign/projects/{project_id}/plan")
    scene_id = plan_response.json()["scenes"][0]["scene_id"]
    tts_response = client.post(
        f"/api/videodesign/projects/{project_id}/tts/generate",
        json={"scene_ids": [scene_id], "provider": "timing_only"},
    )
    assert tts_response.status_code == 200
    assert tts_response.json()["scenes"][0]["tts"]["audio_url"]

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

    async def fake_ytdlp_fail(*args, **kwargs):
        raise RuntimeError("skip yt-dlp in fallback test")

    monkeypatch.setattr(douyin_service, "search", fake_search)
    monkeypatch.setattr(douyin_service.stream_proxy, "download_to_file", fake_download_to_file)
    monkeypatch.setattr(videodesign_service.ytdlp, "download", fake_ytdlp_fail)

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
    assert timeline["items"][0]["source_ref"]["cut_strategy"] == "auto_start"
    assert "overlay_default" in timeline["layers"]
    assert any(item["type"] == "overlay" for item in timeline["items"])
    audio_item = next(item for item in timeline["items"] if item["type"] == "audio")
    assert audio_item["source_ref"]["audio_url"].endswith(f"/scenes/{scene_id}/audio")
    assert audio_item["start_seconds"] == timeline["items"][0]["start_seconds"]

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


def test_videodesign_scene_clip_patch_persists_and_updates_timeline(tmp_path):
    client = TestClient(app)
    project_id = _create_project(client)
    plan_response = client.post(f"/api/videodesign/projects/{project_id}/plan")
    scene_id = plan_response.json()["scenes"][0]["scene_id"]

    project = videodesign_service.store.get(project_id)
    scene = project.scenes[0]
    scene.duration_seconds = 3
    scene.approval_state = "downloaded"
    for placeholder_scene in project.scenes[1:]:
        placeholder_scene.approval_state = "placeholder_allowed"
    asset_path = tmp_path / "scene.mp4"
    asset_path.write_bytes(b"video")
    asset = MaterialAsset(
        asset_id="mat_clip_test",
        project_id=project_id,
        scene_id=scene_id,
        candidate_id="cand_clip_test",
        local_path=str(asset_path),
        duration=10,
    )
    project.material_assets.append(asset)
    scene.material_asset_id = asset.asset_id
    videodesign_service.store.put(project)

    studio_response = client.post(f"/api/videodesign/projects/{project_id}/studio")
    assert studio_response.status_code == 200
    media = next(item for item in studio_response.json()["timeline"]["items"] if item["type"] == "media")
    assert media["source_ref"]["trim_source"] == "auto_start"
    assert media["source_ref"]["trim_start_seconds"] == 0
    assert media["source_ref"]["trim_end_seconds"] == 3

    patch_response = client.patch(
        f"/api/videodesign/projects/{project_id}/scenes/{scene_id}/clip",
        json={
            "material_asset_id": asset.asset_id,
            "trim_source": "manual",
            "trim_start_seconds": 9,
            "asset_duration_seconds": 10,
            "transform": {"flip_horizontal": True},
            "effects": {"contrast": 1.12},
        },
    )
    assert patch_response.status_code == 200
    scene = patch_response.json()["scene"]
    assert scene["clip"]["trim_source"] == "manual"
    assert scene["clip"]["trim_start_seconds"] == 7
    assert scene["clip"]["trim_end_seconds"] == 10
    media = next(item for item in patch_response.json()["timeline"]["items"] if item["type"] == "media")
    assert media["source_ref"]["trim_start_seconds"] == 7
    assert media["source_ref"]["trim_end_seconds"] == 10
    assert media["transform"]["flip_horizontal"] is True
    assert media["source_ref"]["effects"]["contrast"] == 1.12

    short_response = client.patch(
        f"/api/videodesign/projects/{project_id}/scenes/{scene_id}/clip",
        json={
            "material_asset_id": asset.asset_id,
            "trim_source": "manual",
            "trim_start_seconds": 1,
            "asset_duration_seconds": 2,
        },
    )
    assert short_response.status_code == 200
    assert short_response.json()["scene"]["clip"]["trim_start_seconds"] == 0
    assert short_response.json()["scene"]["clip"]["trim_end_seconds"] == 2
    assert short_response.json()["scene"]["clip"]["loop_mode"] == "loop_to_fill"


def test_videodesign_studio_creative_controls_api(tmp_path):
    client = TestClient(app)
    project_id = _create_project(client)
    plan_response = client.post(f"/api/videodesign/projects/{project_id}/plan")
    first_scene_id = plan_response.json()["scenes"][0]["scene_id"]

    project = videodesign_service.store.get(project_id)
    for index, scene in enumerate(project.scenes):
        scene.duration_seconds = 3
        if index < 2:
            scene.approval_state = "downloaded"
            asset_path = tmp_path / f"{scene.scene_id}.mp4"
            asset_path.write_bytes(b"video")
            asset = MaterialAsset(
                asset_id=f"mat_{scene.scene_id}",
                project_id=project_id,
                scene_id=scene.scene_id,
                candidate_id=f"cand_{scene.scene_id}",
                local_path=str(asset_path),
                duration=8,
            )
            project.material_assets.append(asset)
            scene.material_asset_id = asset.asset_id
        else:
            scene.approval_state = "placeholder_allowed"
    videodesign_service.store.put(project)

    studio_response = client.post(f"/api/videodesign/projects/{project_id}/studio")
    assert studio_response.status_code == 200

    icon_response = client.post(
        f"/api/videodesign/projects/{project_id}/timeline/items",
        json={
            "scene_id": first_scene_id,
            "type": "icon",
            "layer_id": "icon",
            "start_seconds": 0.5,
            "end_seconds": 2.2,
            "source_ref": {"icon_id": "arrow_right"},
            "transform": {"x": 62, "y": 40, "scale": 1.2},
            "style": {"color": "#ffffff"},
        },
    )
    assert icon_response.status_code == 200
    assert icon_response.json()["item"]["type"] == "icon"
    assert "icon" in icon_response.json()["timeline"]["layers"]

    overlay_response = client.post(
        f"/api/videodesign/projects/{project_id}/timeline/items",
        json={
            "scene_id": first_scene_id,
            "type": "overlay",
            "layer_id": "overlay_default",
            "source_ref": {"overlay_id": "caption_shade"},
            "style": {"overlay_id": "caption_shade", "opacity": 0.4},
        },
    )
    assert overlay_response.status_code == 200
    assert overlay_response.json()["item"]["start_seconds"] == 0
    assert overlay_response.json()["item"]["end_seconds"] == 3

    delete_response = client.delete(
        f"/api/videodesign/projects/{project_id}/timeline/items/{icon_response.json()['item']['item_id']}"
    )
    assert delete_response.status_code == 200
    assert all(item["item_id"] != icon_response.json()["item"]["item_id"] for item in delete_response.json()["timeline"]["items"])

    transition_response = client.post(
        f"/api/videodesign/projects/{project_id}/scenes/{first_scene_id}/transition",
        json={"transition_id": "fade", "duration_seconds": 0.25},
    )
    assert transition_response.status_code == 200
    transition = next(item for item in transition_response.json()["timeline"]["items"] if item["type"] == "transition")
    assert transition["source_ref"]["transition_id"] == "fade"

    apply_all_response = client.post(
        f"/api/videodesign/projects/{project_id}/transitions/apply-all",
        json={"transition_id": "slide_left", "duration_seconds": 0.35},
    )
    assert apply_all_response.status_code == 200
    transitions = [item for item in apply_all_response.json()["timeline"]["items"] if item["type"] == "transition"]
    assert transitions
    assert all(item["source_ref"]["transition_id"] == "slide_left" for item in transitions)

    random_response = client.post(f"/api/videodesign/projects/{project_id}/transitions/randomize")
    assert random_response.status_code == 200
    assert any(item["type"] == "transition" for item in random_response.json()["timeline"]["items"])
