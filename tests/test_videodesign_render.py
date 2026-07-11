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
