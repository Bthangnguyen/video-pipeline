from pathlib import Path

from fastapi.routing import APIRoute
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
from app.videodesign.schemas import MaterialAsset, MediaCandidate, SmoothPreview, SplitSettings, VideoDesignProject
import app.videodesign.service as videodesign_service_module
from app.videodesign.service import _download_source_url, videodesign_service
from tests.videodesign_helpers import create_project as _create_project, write_test_wav as _write_test_wav


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


def test_videodesign_progress_endpoint_defaults_to_idle():
    client = TestClient(app)
    project_id = _create_project(client)

    response = client.get(f"/api/videodesign/projects/{project_id}/progress")

    assert response.status_code == 200
    progress = response.json()["progress"]
    assert progress["stage"] == "idle"
    assert progress["current"] == 0
    assert progress["total"] == 0


def test_videodesign_route_contract():
    expected = {
        ("GET", "/api/videodesign/health"),
        ("GET", "/api/videodesign/projects"),
        ("POST", "/api/videodesign/projects"),
        ("GET", "/api/videodesign/projects/{project_id}"),
        ("PATCH", "/api/videodesign/projects/{project_id}"),
        ("PATCH", "/api/videodesign/projects/{project_id}/preset"),
        ("PATCH", "/api/videodesign/projects/{project_id}/split-settings"),
        ("POST", "/api/videodesign/projects/{project_id}/script/generate"),
        ("POST", "/api/videodesign/projects/{project_id}/plan"),
        ("PATCH", "/api/videodesign/projects/{project_id}/scenes/{scene_id}"),
        ("PATCH", "/api/videodesign/projects/{project_id}/scenes/{scene_id}/clip"),
        ("POST", "/api/videodesign/projects/{project_id}/scenes/{scene_id}/split"),
        ("POST", "/api/videodesign/projects/{project_id}/scenes/merge"),
        ("POST", "/api/videodesign/projects/{project_id}/tts/generate"),
        ("DELETE", "/api/videodesign/projects/{project_id}/tts"),
        ("POST", "/api/videodesign/projects/{project_id}/keywords/generate"),
        ("PATCH", "/api/videodesign/projects/{project_id}/search-plan"),
        ("GET", "/api/videodesign/projects/{project_id}/scenes/{scene_id}/audio"),
        ("POST", "/api/videodesign/projects/{project_id}/audio/combined"),
        ("GET", "/api/videodesign/projects/{project_id}/audio/combined"),
        ("POST", "/api/videodesign/projects/{project_id}/materials/search"),
        ("POST", "/api/videodesign/materials/preflight"),
        ("POST", "/api/videodesign/projects/{project_id}/scenes/{scene_id}/materials/search"),
        ("GET", "/api/videodesign/projects/{project_id}/review"),
        ("GET", "/api/videodesign/projects/{project_id}/progress"),
        ("PATCH", "/api/videodesign/projects/{project_id}/scenes/{scene_id}/selection"),
        ("POST", "/api/videodesign/projects/{project_id}/materials/download"),
        ("POST", "/api/videodesign/projects/{project_id}/materials/prune"),
        ("GET", "/api/videodesign/projects/{project_id}/materials/{asset_id}/file"),
        ("GET", "/api/videodesign/projects/{project_id}/materials/{asset_id}/proxy"),
        ("POST", "/api/videodesign/projects/{project_id}/studio"),
        ("GET", "/api/videodesign/projects/{project_id}/timeline"),
        ("DELETE", "/api/videodesign/projects/{project_id}/timeline"),
        ("GET", "/api/videodesign/sfx/catalog"),
        ("GET", "/api/videodesign/sfx/{asset_id}/file"),
        ("POST", "/api/videodesign/projects/{project_id}/sfx/suggest"),
        ("GET", "/api/videodesign/projects/{project_id}/sfx/suggestions"),
        ("POST", "/api/videodesign/projects/{project_id}/sfx/apply"),
        ("GET", "/api/videodesign/projects/{project_id}/preview"),
        ("POST", "/api/videodesign/projects/{project_id}/preview/render"),
        ("GET", "/api/videodesign/projects/{project_id}/preview/file"),
        ("POST", "/api/videodesign/projects/{project_id}/export/render"),
        ("GET", "/api/videodesign/projects/{project_id}/export/file"),
        ("POST", "/api/videodesign/projects/{project_id}/music/upload"),
        ("GET", "/api/videodesign/projects/{project_id}/music/{item_id}/file"),
        ("POST", "/api/videodesign/projects/{project_id}/timeline/items"),
        ("PATCH", "/api/videodesign/projects/{project_id}/timeline/items/{item_id}"),
        ("DELETE", "/api/videodesign/projects/{project_id}/timeline/items/{item_id}"),
        ("POST", "/api/videodesign/projects/{project_id}/scenes/{scene_id}/transition"),
        ("POST", "/api/videodesign/projects/{project_id}/transitions/apply-all"),
        ("POST", "/api/videodesign/projects/{project_id}/transitions/randomize"),
    }
    actual = {
        (method, route.path)
        for route in app.routes
        if isinstance(route, APIRoute) and route.path.startswith("/api/videodesign")
        for method in route.methods
    }

    assert actual == expected


def test_videodesign_legacy_project_payload_uses_current_defaults():
    project = VideoDesignProject.model_validate(
        {
            "project_id": "vdp_legacy_contract",
            "script": "A legacy project created before search pools and smooth previews.",
            "scenes": [
                {
                    "scene_id": "scn_legacy",
                    "order": 1,
                    "voiceover_text": "A legacy scene remains readable.",
                    "matching_keywords": ["japan life"],
                }
            ],
            "created_at": "2026-01-01T00:00:00+00:00",
        }
    )

    assert project.material_search_plan.popular_first is True
    assert project.material_search_plan.groups == []
    assert project.voiceover_track.scene_offsets == []
    assert project.smooth_preview.status == "missing"
    assert project.scenes[0].search_group_id == ""
    assert project.scenes[0].clip is None
