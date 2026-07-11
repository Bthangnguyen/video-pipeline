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
