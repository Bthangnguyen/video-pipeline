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
