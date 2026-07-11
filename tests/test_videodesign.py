from pathlib import Path
import math
import wave

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


def _write_test_wav(path: Path, duration_seconds: float = 0.5) -> None:
    sample_rate = 16000
    frame_count = max(1, int(sample_rate * duration_seconds))
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        frames = bytearray()
        for index in range(frame_count):
            sample = int(math.sin(2 * math.pi * 440 * (index / sample_rate)) * 8000)
            frames.extend(sample.to_bytes(2, "little", signed=True))
        wav.writeframes(bytes(frames))


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


def test_videodesign_tts_timing_only_generates_global_voiceover():
    client = TestClient(app)
    project_id = _create_project(client)
    client.post(f"/api/videodesign/projects/{project_id}/plan")

    response = client.post(
        f"/api/videodesign/projects/{project_id}/tts/generate",
        json={"provider": "timing_only", "voice_id": "test"},
    )

    assert response.status_code == 200
    body = response.json()
    track = body["voiceover_track"]
    assert track["audio_url"].endswith(f"/projects/{project_id}/audio/combined")
    assert track["scene_offsets"]
    assert track["scene_offsets"][0]["start_seconds"] == 0
    project = videodesign_service.store.get(project_id)
    audio_duration = measure_audio_duration(project.voiceover_track.audio_path)
    assert abs(audio_duration - track["duration_seconds"]) < 0.1
    for scene in body["scenes"]:
        assert scene["tts"]["sync_state"] == "synced"
        assert scene["tts"]["audio_path"] == ""
        assert scene["caption_chunks"]
        assert scene["duration_seconds"] > 0


def test_videodesign_tts_can_regenerate_single_scene_audio():
    client = TestClient(app)
    project_id = _create_project(client)
    plan_response = client.post(f"/api/videodesign/projects/{project_id}/plan")
    scene_id = plan_response.json()["scenes"][0]["scene_id"]

    response = client.post(
        f"/api/videodesign/projects/{project_id}/tts/generate",
        json={"scene_ids": [scene_id], "provider": "timing_only", "voice_id": "test"},
    )

    assert response.status_code == 200
    scene = response.json()["scenes"][0]
    assert scene["tts"]["audio_url"].endswith(f"/scenes/{scene_id}/audio")
    assert scene["tts"]["sync_state"] == "synced"
    project = videodesign_service.store.get(project_id)
    audio_duration = measure_audio_duration(project.scenes[0].tts.audio_path)
    assert abs(audio_duration - scene["duration_seconds"]) < 0.1


def test_videodesign_combined_voiceover_requires_scene_audio():
    client = TestClient(app)
    project_id = _create_project(client)
    client.post(f"/api/videodesign/projects/{project_id}/plan")

    response = client.post(f"/api/videodesign/projects/{project_id}/audio/combined")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "AUDIO_NOT_FOUND"


def test_videodesign_combined_voiceover_offsets_and_streams():
    client = TestClient(app)
    project_id = _create_project(client)
    plan_response = client.post(f"/api/videodesign/projects/{project_id}/plan")
    scene_count = len(plan_response.json()["scenes"])
    tts_response = client.post(
        f"/api/videodesign/projects/{project_id}/tts/generate",
        json={"provider": "timing_only", "voice_id": "test"},
    )
    assert tts_response.status_code == 200

    response = client.post(f"/api/videodesign/projects/{project_id}/audio/combined")

    assert response.status_code == 200
    track = response.json()["voiceover_track"]
    assert track["audio_url"].endswith(f"/projects/{project_id}/audio/combined")
    assert len(track["scene_offsets"]) == scene_count
    assert track["scene_offsets"][0]["start_seconds"] == 0
    assert track["duration_seconds"] >= track["scene_offsets"][-1]["end_seconds"] - 0.1

    audio_response = client.get(track["audio_url"])
    assert audio_response.status_code == 200
    assert audio_response.content


def test_videodesign_studio_uses_global_voiceover_offsets(tmp_path):
    client = TestClient(app)
    project_id = _create_project(client)
    client.post(f"/api/videodesign/projects/{project_id}/plan")
    tts_response = client.post(
        f"/api/videodesign/projects/{project_id}/tts/generate",
        json={"provider": "timing_only", "voice_id": "test"},
    )
    assert tts_response.status_code == 200
    offsets = {
        offset["scene_id"]: offset
        for offset in tts_response.json()["voiceover_track"]["scene_offsets"]
    }

    project = videodesign_service.store.get(project_id)
    for scene in project.scenes:
        asset_path = tmp_path / f"{scene.scene_id}.mp4"
        asset_path.write_bytes(b"video")
        asset = MaterialAsset(
            asset_id=f"mat_{scene.scene_id}",
            project_id=project_id,
            scene_id=scene.scene_id,
            candidate_id=f"cand_{scene.scene_id}",
            local_path=str(asset_path),
            duration=20,
        )
        project.material_assets.append(asset)
        scene.material_asset_id = asset.asset_id
        scene.approval_state = "downloaded"
    videodesign_service.store.put(project)

    studio_response = client.post(f"/api/videodesign/projects/{project_id}/studio")

    assert studio_response.status_code == 200
    timeline = studio_response.json()["timeline"]
    assert timeline["duration_seconds"] == round(tts_response.json()["voiceover_track"]["duration_seconds"], 2)
    media_items = [item for item in timeline["items"] if item["type"] == "media"]
    assert len(media_items) == len(offsets)
    for item in media_items:
        offset = offsets[item["scene_id"]]
        assert item["start_seconds"] == round(offset["start_seconds"], 2)
        assert item["end_seconds"] == round(offset["end_seconds"], 2)


def test_videodesign_create_studio_backfills_preview_proxy(monkeypatch, tmp_path):
    client = TestClient(app)
    project_id = _create_project(client)
    plan_response = client.post(f"/api/videodesign/projects/{project_id}/plan")
    scene_id = plan_response.json()["scenes"][0]["scene_id"]

    async def fake_create_preview_proxy(asset, aspect_ratio):
        proxy_path = tmp_path / f"{asset.asset_id}_proxy.mp4"
        proxy_path.write_bytes(b"proxy-video")
        return proxy_path

    monkeypatch.setattr(videodesign_service_module, "_create_preview_proxy", fake_create_preview_proxy)

    project = videodesign_service.store.get(project_id)
    scene = project.scenes[0]
    scene.duration_seconds = 3
    scene.approval_state = "downloaded"
    for placeholder_scene in project.scenes[1:]:
        placeholder_scene.approval_state = "placeholder_allowed"
    asset_path = tmp_path / "scene.mp4"
    asset_path.write_bytes(b"downloaded-video")
    asset = MaterialAsset(
        asset_id="mat_proxy_test",
        project_id=project_id,
        scene_id=scene_id,
        candidate_id="cand_proxy_test",
        local_path=str(asset_path),
        duration=10,
    )
    project.material_assets.append(asset)
    scene.material_asset_id = asset.asset_id
    videodesign_service.store.put(project)

    studio_response = client.post(f"/api/videodesign/projects/{project_id}/studio")

    assert studio_response.status_code == 200
    project = videodesign_service.store.get(project_id)
    assert project.material_assets[0].proxy_path.endswith("_proxy.mp4")
    media = next(item for item in studio_response.json()["timeline"]["items"] if item["type"] == "media")
    assert media["source_ref"]["media_url"].endswith("/materials/mat_proxy_test/proxy")
    assert media["source_ref"]["proxy_media_url"].endswith("/materials/mat_proxy_test/proxy")


def test_videodesign_clear_timeline_keeps_project_materials(tmp_path):
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
    asset_path.write_bytes(b"downloaded-video")
    asset = MaterialAsset(
        asset_id="mat_clear_timeline",
        project_id=project_id,
        scene_id=scene_id,
        candidate_id="cand_clear_timeline",
        local_path=str(asset_path),
        duration=10,
    )
    project.material_assets.append(asset)
    scene.material_asset_id = asset.asset_id
    videodesign_service.store.put(project)

    studio_response = client.post(f"/api/videodesign/projects/{project_id}/studio")
    assert studio_response.status_code == 200

    response = client.delete(f"/api/videodesign/projects/{project_id}/timeline")

    assert response.status_code == 200
    assert response.json()["timeline"] is None
    project = videodesign_service.store.get(project_id)
    assert project.timeline is None
    assert project.material_assets[0].asset_id == "mat_clear_timeline"
    assert project.scenes[0].material_asset_id == "mat_clear_timeline"


def test_videodesign_smooth_preview_render_file_and_stale_state(monkeypatch, tmp_path):
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
    asset_path.write_bytes(b"downloaded-video")
    asset = MaterialAsset(
        asset_id="mat_preview_test",
        project_id=project_id,
        scene_id=scene_id,
        candidate_id="cand_preview_test",
        local_path=str(asset_path),
        duration=10,
    )
    project.material_assets.append(asset)
    scene.material_asset_id = asset.asset_id
    videodesign_service.store.put(project)

    async def fake_render_preview(project):
        preview_path = tmp_path / "timeline_preview.mp4"
        preview_path.write_bytes(b"preview-video")
        return preview_path

    monkeypatch.setattr(videodesign_service_module, "_render_smooth_preview_file", fake_render_preview)

    studio_response = client.post(f"/api/videodesign/projects/{project_id}/studio")
    assert studio_response.status_code == 200

    render_response = client.post(f"/api/videodesign/projects/{project_id}/preview/render")

    assert render_response.status_code == 200
    preview = render_response.json()["preview"]
    assert preview["status"] == "ready"
    assert preview["preview_url"].endswith("/preview/file?v=" + preview["updated_at"].replace("-", "").replace(":", "").replace(".", "").replace("+", ""))

    file_response = client.get(preview["preview_url"])
    assert file_response.status_code == 200
    assert file_response.content == b"preview-video"

    text_item = next(item for item in studio_response.json()["timeline"]["items"] if item["type"] == "text")
    patch_response = client.patch(
        f"/api/videodesign/projects/{project_id}/timeline/items/{text_item['item_id']}",
        json={"source_ref": {"text": "Preview stale now"}},
    )

    assert patch_response.status_code == 200
    assert videodesign_service.store.get(project_id).smooth_preview.status == "stale"


def test_videodesign_sfx_catalog_suggest_and_apply(tmp_path):
    client = TestClient(app)
    project_id = _create_project(client)
    plan_response = client.post(f"/api/videodesign/projects/{project_id}/plan")
    assert plan_response.status_code == 200

    catalog_response = client.get("/api/videodesign/sfx/catalog")
    assert catalog_response.status_code == 200
    catalog = catalog_response.json()["items"]
    transition_presets = catalog_response.json()["transition_presets"]
    assert any(item["asset_id"] == "mixkit_whoosh_fast_whoosh_transition" for item in catalog)
    assert not any(item["asset_id"] == "sfx_whoosh_short" for item in catalog)
    assert next(item for item in transition_presets if item["transition_id"] == "none")["enabled"] is False
    assert next(item for item in transition_presets if item["transition_id"] == "slide_left")["volume"] > 0
    file_response = client.get("/api/videodesign/sfx/mixkit_whoosh_fast_whoosh_transition/file")
    assert file_response.status_code == 200
    assert file_response.content

    project = videodesign_service.store.get(project_id)
    for index, scene in enumerate(project.scenes):
        if index < 2:
            scene.duration_seconds = 2
            scene.approval_state = "downloaded"
            asset_path = tmp_path / f"{scene.scene_id}.mp4"
            asset_path.write_bytes(b"video")
            asset = MaterialAsset(
                asset_id=f"mat_sfx_{index}",
                project_id=project_id,
                scene_id=scene.scene_id,
                candidate_id=f"cand_sfx_{index}",
                local_path=str(asset_path),
                duration=10,
            )
            project.material_assets.append(asset)
            scene.material_asset_id = asset.asset_id
        else:
            scene.approval_state = "placeholder_allowed"
    videodesign_service.store.put(project)

    studio_response = client.post(f"/api/videodesign/projects/{project_id}/studio")
    assert studio_response.status_code == 200

    suggest_response = client.post(
        f"/api/videodesign/projects/{project_id}/sfx/suggest",
        json={"max_suggestions": 6, "include_caption_words": True, "include_transitions": True},
    )
    assert suggest_response.status_code == 200
    suggestions = suggest_response.json()["suggestions"]
    assert suggestions
    assert any(item["event_type"] == "transition" for item in suggestions)

    transition_suggestion = next(item for item in suggestions if item["event_type"] == "transition")
    selected = [transition_suggestion["suggestion_id"]]
    apply_response = client.post(
        f"/api/videodesign/projects/{project_id}/sfx/apply",
        json={"suggestion_ids": selected, "volume_overrides": {selected[0]: 0.12}},
    )

    assert apply_response.status_code == 200
    timeline = apply_response.json()["timeline"]
    assert "sfx" in timeline["layers"]
    sfx_items = [item for item in timeline["items"] if item["type"] == "sfx"]
    assert len(sfx_items) == 1
    assert sfx_items[0]["source_ref"]["asset_id"]
    assert sfx_items[0]["style"]["volume"] == 0.12
    assert sfx_items[0]["end_seconds"] - sfx_items[0]["start_seconds"] <= transition_suggestion["duration_hint_seconds"] + 0.01
    assert videodesign_service.store.get(project_id).smooth_preview.status in {"missing", "stale"}


def test_videodesign_background_music_upload_patch_and_file(tmp_path):
    client = TestClient(app)
    project_id = _create_project(client)
    plan_response = client.post(f"/api/videodesign/projects/{project_id}/plan")
    assert plan_response.status_code == 200

    project = videodesign_service.store.get(project_id)
    for index, scene in enumerate(project.scenes):
        if index < 2:
            scene.duration_seconds = 2
            scene.approval_state = "downloaded"
            asset_path = tmp_path / f"{scene.scene_id}.mp4"
            asset_path.write_bytes(b"video")
            asset = MaterialAsset(
                asset_id=f"mat_music_{index}",
                project_id=project_id,
                scene_id=scene.scene_id,
                candidate_id=f"cand_music_{index}",
                local_path=str(asset_path),
                duration=10,
            )
            project.material_assets.append(asset)
            scene.material_asset_id = asset.asset_id
        else:
            scene.approval_state = "placeholder_allowed"
    videodesign_service.store.put(project)

    studio_response = client.post(f"/api/videodesign/projects/{project_id}/studio")
    assert studio_response.status_code == 200

    music_path = tmp_path / "music.wav"
    _write_test_wav(music_path)
    upload_response = client.post(
        f"/api/videodesign/projects/{project_id}/music/upload",
        files={"file": ("music.wav", music_path.read_bytes(), "audio/wav")},
    )
    assert upload_response.status_code == 200
    timeline = upload_response.json()["timeline"]
    music_items = [item for item in timeline["items"] if item["type"] == "music"]
    assert len(music_items) == 1
    assert music_items[0]["layer_id"] == "background_audio"
    assert music_items[0]["style"]["ducking"] is True

    file_response = client.get(music_items[0]["source_ref"]["audio_url"])
    assert file_response.status_code == 200
    assert file_response.content

    patch_response = client.patch(
        f"/api/videodesign/projects/{project_id}/timeline/items/{music_items[0]['item_id']}",
        json={
            "style": {**music_items[0]["style"], "volume": 0.22, "ducking_volume": 0.09},
            "source_ref": {**music_items[0]["source_ref"], "trim_start_seconds": 0.1, "trim_end_seconds": 0.4},
        },
    )
    assert patch_response.status_code == 200
    assert patch_response.json()["item"]["style"]["volume"] == 0.22
    assert patch_response.json()["item"]["source_ref"]["trim_start_seconds"] == 0.1
    assert patch_response.json()["item"]["source_ref"]["trim_end_seconds"] == 0.4


def test_videodesign_clear_tts_resets_audio_files_and_voiceover():
    client = TestClient(app)
    project_id = _create_project(client)
    client.post(f"/api/videodesign/projects/{project_id}/plan")
    tts_response = client.post(
        f"/api/videodesign/projects/{project_id}/tts/generate",
        json={"provider": "timing_only", "voice_id": "test"},
    )
    assert tts_response.status_code == 200
    combined_response = client.post(f"/api/videodesign/projects/{project_id}/audio/combined")
    assert combined_response.status_code == 200

    project = videodesign_service.store.get(project_id)
    scene_audio_paths = [Path(scene.tts.audio_path) for scene in project.scenes if scene.tts.audio_path]
    combined_path = Path(project.voiceover_track.audio_path)
    assert all(path.exists() for path in scene_audio_paths)
    assert combined_path.exists()

    response = client.delete(f"/api/videodesign/projects/{project_id}/tts")

    assert response.status_code == 200
    body = response.json()
    assert body["deleted_files"] >= len(scene_audio_paths)
    assert body["project"]["voiceover_track"]["audio_url"] == ""
    assert body["project"]["timeline"] is None
    assert all(scene["tts"]["sync_state"] == "pending" for scene in body["scenes"])
    assert all(scene["tts"]["audio_path"] == "" for scene in body["scenes"])
    assert all(not path.exists() for path in scene_audio_paths)
    assert not combined_path.exists()


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


def test_videodesign_lists_saved_projects():
    client = TestClient(app)
    project_id = _create_project(client)

    response = client.get("/api/videodesign/projects")

    assert response.status_code == 200
    projects = response.json()["projects"]
    summary = next(item for item in projects if item["project_id"] == project_id)
    assert summary["title"].startswith("Cats can recognize")
    assert summary["stage"] == "script"
    assert summary["scene_count"] == 0


def test_videodesign_export_file_uses_smooth_preview(tmp_path):
    client = TestClient(app)
    project_id = _create_project(client)
    export_path = tmp_path / "timeline_preview.mp4"
    export_path.write_bytes(b"export-video")

    project = videodesign_service.store.get(project_id)
    project.smooth_preview = SmoothPreview(
        status="ready",
        preview_url=f"/api/videodesign/projects/{project_id}/preview/file?v=test",
        preview_path=str(export_path),
        timeline_id="tln_test",
        duration_seconds=3,
        updated_at="2026-01-01T00:00:00+00:00",
    )
    videodesign_service.store.put(project)

    response = client.get(f"/api/videodesign/projects/{project_id}/export/file")

    assert response.status_code == 200
    assert response.content == b"export-video"
    assert response.headers["content-type"].startswith("video/mp4")


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


def test_videodesign_download_persists_completed_scene_when_later_scene_fails(monkeypatch):
    client = TestClient(app)
    project_id = _create_project(client)
    plan_response = client.post(f"/api/videodesign/projects/{project_id}/plan")
    scene_ids = [scene["scene_id"] for scene in plan_response.json()["scenes"][:2]]

    project = videodesign_service.store.get(project_id)
    for index, scene_id in enumerate(scene_ids):
        candidate = MediaCandidate(
            candidate_id=f"cand-partial-{index}",
            source="douyinsearch",
            scene_id=scene_id,
            source_result_id=f"result-partial-{index}",
            source_item_id=f"aweme-partial-{index}",
            douyin_result_id=f"result-partial-{index}",
            douyin_aweme_id=f"aweme-partial-{index}",
            remote_download_url=f"https://example.com/{index}.mp4",
            status="approved",
        )
        scene = next(item for item in project.scenes if item.scene_id == scene_id)
        project.candidates.append(candidate)
        scene.selected_candidate_id = candidate.candidate_id
        scene.approval_state = "approved"
    videodesign_service.store.put(project)

    async def fake_download(candidate, output_path):
        if candidate.candidate_id == "cand-partial-1":
            raise RuntimeError("network dropped")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"video")

    async def fake_proxy(asset, aspect_ratio):
        return None

    monkeypatch.setattr(videodesign_service, "_download_candidate", fake_download)
    monkeypatch.setattr(videodesign_service_module, "_ensure_preview_proxy", fake_proxy)

    response = client.post(
        f"/api/videodesign/projects/{project_id}/materials/download",
        json={"scene_ids": scene_ids},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == DOWNLOAD_FAILED
    project = videodesign_service.store.get(project_id)
    first_scene = next(item for item in project.scenes if item.scene_id == scene_ids[0])
    second_scene = next(item for item in project.scenes if item.scene_id == scene_ids[1])
    assert first_scene.material_asset_id
    assert first_scene.approval_state == "downloaded"
    assert second_scene.material_asset_id is None
    assert second_scene.approval_state == "approved"
    assert project.progress.stage == "materials_download_failed"


def test_videodesign_download_recovers_existing_scene_file(monkeypatch, tmp_path):
    client = TestClient(app)
    project_id = _create_project(client)
    plan_response = client.post(f"/api/videodesign/projects/{project_id}/plan")
    scene_id = plan_response.json()["scenes"][0]["scene_id"]

    project = videodesign_service.store.get(project_id)
    scene = next(item for item in project.scenes if item.scene_id == scene_id)
    candidate = MediaCandidate(
        candidate_id="cand-recover-file",
        source="douyinsearch",
        scene_id=scene_id,
        source_result_id="recover-result",
        source_item_id="recover-aweme",
        douyin_result_id="recover-result",
        douyin_aweme_id="recover-aweme",
        status="approved",
    )
    project.candidates.append(candidate)
    scene.selected_candidate_id = candidate.candidate_id
    scene.approval_state = "approved"
    existing_path = videodesign_service_module.settings.storage_dir / project_id / "materials" / f"{scene_id}.mp4"
    existing_path.parent.mkdir(parents=True, exist_ok=True)
    existing_path.write_bytes(b"already-downloaded")
    videodesign_service.store.put(project)

    async def fail_if_called(*args, **kwargs):
        raise AssertionError("existing file should be recovered without re-downloading")

    async def fake_proxy(asset, aspect_ratio):
        return None

    monkeypatch.setattr(videodesign_service, "_download_candidate", fail_if_called)
    monkeypatch.setattr(videodesign_service_module, "_ensure_preview_proxy", fake_proxy)

    response = client.post(
        f"/api/videodesign/projects/{project_id}/materials/download",
        json={"scene_ids": [scene_id]},
    )

    assert response.status_code == 200
    asset = response.json()["assets"][0]
    assert asset["candidate_id"] == "cand-recover-file"
    project = videodesign_service.store.get(project_id)
    scene = next(item for item in project.scenes if item.scene_id == scene_id)
    assert scene.material_asset_id == asset["asset_id"]
    assert scene.approval_state == "downloaded"


def test_videodesign_download_recovers_existing_scene_file_without_candidate(monkeypatch):
    client = TestClient(app)
    project_id = _create_project(client)
    plan_response = client.post(f"/api/videodesign/projects/{project_id}/plan")
    scene_id = plan_response.json()["scenes"][0]["scene_id"]

    project = videodesign_service.store.get(project_id)
    scene = next(item for item in project.scenes if item.scene_id == scene_id)
    scene.approval_state = "searching"
    existing_path = videodesign_service_module.settings.storage_dir / project_id / "materials" / f"{scene_id}.mp4"
    existing_path.parent.mkdir(parents=True, exist_ok=True)
    existing_path.write_bytes(b"already-downloaded")
    videodesign_service.store.put(project)

    async def fail_if_called(*args, **kwargs):
        raise AssertionError("existing file should be recovered without re-downloading")

    async def fake_proxy(asset, aspect_ratio):
        return None

    monkeypatch.setattr(videodesign_service, "_download_candidate", fail_if_called)
    monkeypatch.setattr(videodesign_service_module, "_ensure_preview_proxy", fake_proxy)

    response = client.post(
        f"/api/videodesign/projects/{project_id}/materials/download",
        json={"scene_ids": [scene_id]},
    )

    assert response.status_code == 200
    asset = response.json()["assets"][0]
    assert asset["source"] == "recovered"
    project = videodesign_service.store.get(project_id)
    scene = next(item for item in project.scenes if item.scene_id == scene_id)
    assert scene.selected_candidate_id
    assert scene.material_asset_id == asset["asset_id"]
    assert scene.approval_state == "downloaded"


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
