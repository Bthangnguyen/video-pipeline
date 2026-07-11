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
