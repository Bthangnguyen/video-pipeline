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
