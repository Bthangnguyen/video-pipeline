from pathlib import Path

from fastapi import APIRouter, Body
from fastapi.responses import FileResponse, JSONResponse

from app.videodesign.errors import AUDIO_NOT_FOUND, PROJECT_NOT_FOUND, SCENE_NOT_FOUND, VideoDesignError
from app.videodesign.schemas import (
    CreateProjectRequest,
    KeywordGenerateRequest,
    MaterialsDownloadRequest,
    MaterialsPreflightRequest,
    MaterialsPruneRequest,
    MaterialsSearchRequest,
    SceneClipPatch,
    SceneSelectionRequest,
    ScriptGenerateRequest,
    SplitSettings,
    TimelineItemCreateRequest,
    TimelineItemPatch,
    TransitionRequest,
    TTSGenerateRequest,
)
from app.videodesign.service import videodesign_service

router = APIRouter()


def error_response(error: VideoDesignError):
    status_code = 404 if error.code in (PROJECT_NOT_FOUND, SCENE_NOT_FOUND) else 400
    return JSONResponse(status_code=status_code, content={"success": False, "error": error.to_payload()})


@router.get("/health")
async def health():
    return videodesign_service.health()


@router.post("/projects")
async def create_project(request: CreateProjectRequest):
    try:
        return videodesign_service.create_project(request)
    except VideoDesignError as error:
        return error_response(error)


@router.get("/projects/{project_id}")
async def get_project(project_id: str):
    try:
        return videodesign_service.get_project(project_id)
    except VideoDesignError as error:
        return error_response(error)


@router.patch("/projects/{project_id}")
async def update_project(project_id: str, patch: dict = Body(...)):
    try:
        return videodesign_service.update_project(project_id, patch)
    except VideoDesignError as error:
        return error_response(error)


@router.patch("/projects/{project_id}/preset")
async def set_preset(project_id: str, preset: dict = Body(...)):
    try:
        return videodesign_service.set_preset(project_id, preset)
    except VideoDesignError as error:
        return error_response(error)


@router.patch("/projects/{project_id}/split-settings")
async def set_split_settings(project_id: str, request: SplitSettings):
    try:
        return videodesign_service.set_split_settings(project_id, request)
    except VideoDesignError as error:
        return error_response(error)


@router.post("/projects/{project_id}/script/generate")
async def generate_script(project_id: str, request: ScriptGenerateRequest):
    try:
        return await videodesign_service.generate_script(project_id, request)
    except VideoDesignError as error:
        return error_response(error)


@router.post("/projects/{project_id}/plan")
async def plan(project_id: str):
    try:
        return videodesign_service.plan(project_id)
    except VideoDesignError as error:
        return error_response(error)


@router.patch("/projects/{project_id}/scenes/{scene_id}")
async def update_scene(project_id: str, scene_id: str, patch: dict = Body(...)):
    try:
        return videodesign_service.update_scene(project_id, scene_id, patch)
    except VideoDesignError as error:
        return error_response(error)


@router.patch("/projects/{project_id}/scenes/{scene_id}/clip")
async def update_scene_clip(project_id: str, scene_id: str, request: SceneClipPatch):
    try:
        return videodesign_service.update_scene_clip(project_id, scene_id, request)
    except VideoDesignError as error:
        return error_response(error)


@router.post("/projects/{project_id}/scenes/{scene_id}/split")
async def split_scene(project_id: str, scene_id: str):
    try:
        return videodesign_service.split_scene(project_id, scene_id)
    except VideoDesignError as error:
        return error_response(error)


@router.post("/projects/{project_id}/scenes/merge")
async def merge_scenes(project_id: str, payload: dict = Body(...)):
    try:
        return videodesign_service.merge_scenes(project_id, payload.get("scene_ids", []))
    except VideoDesignError as error:
        return error_response(error)


@router.post("/projects/{project_id}/tts/generate")
async def generate_tts(project_id: str, request: TTSGenerateRequest):
    try:
        return await videodesign_service.generate_tts(project_id, request)
    except VideoDesignError as error:
        return error_response(error)


@router.delete("/projects/{project_id}/tts")
async def clear_tts(project_id: str):
    try:
        return videodesign_service.clear_tts(project_id)
    except VideoDesignError as error:
        return error_response(error)


@router.post("/projects/{project_id}/keywords/generate")
async def generate_keywords(project_id: str, request: KeywordGenerateRequest):
    try:
        return await videodesign_service.generate_scene_keywords(project_id, request)
    except VideoDesignError as error:
        return error_response(error)


@router.get("/projects/{project_id}/scenes/{scene_id}/audio")
async def scene_audio(project_id: str, scene_id: str):
    try:
        project = videodesign_service.store.get(project_id)
        scene = next((item for item in project.scenes if item.scene_id == scene_id), None)
        if not scene:
            raise VideoDesignError(SCENE_NOT_FOUND, "Scene does not exist.")
        if not scene.tts.audio_path:
            raise VideoDesignError(AUDIO_NOT_FOUND, "Scene audio has not been generated.")
        path = Path(scene.tts.audio_path)
        return FileResponse(path, media_type="audio/mpeg" if path.suffix == ".mp3" else "audio/wav")
    except VideoDesignError as error:
        return error_response(error)


@router.post("/projects/{project_id}/audio/combined")
async def build_combined_voiceover(project_id: str):
    try:
        return videodesign_service.build_combined_voiceover(project_id)
    except VideoDesignError as error:
        return error_response(error)


@router.get("/projects/{project_id}/audio/combined")
async def combined_voiceover(project_id: str):
    try:
        path = videodesign_service.combined_voiceover_path(project_id)
        return FileResponse(path, media_type="audio/mpeg" if path.suffix == ".mp3" else "audio/wav")
    except VideoDesignError as error:
        return error_response(error)


@router.post("/projects/{project_id}/materials/search")
async def search_materials(project_id: str, request: MaterialsSearchRequest):
    try:
        return await videodesign_service.search_materials(project_id, request)
    except VideoDesignError as error:
        return error_response(error)


@router.post("/materials/preflight")
async def materials_preflight(request: MaterialsPreflightRequest):
    try:
        return await videodesign_service.materials_preflight(request)
    except VideoDesignError as error:
        return error_response(error)


@router.post("/projects/{project_id}/scenes/{scene_id}/materials/search")
async def search_scene_materials(project_id: str, scene_id: str, request: MaterialsSearchRequest):
    try:
        request.scene_ids = [scene_id]
        return await videodesign_service.search_materials(project_id, request)
    except VideoDesignError as error:
        return error_response(error)


@router.get("/projects/{project_id}/review")
async def review(project_id: str):
    try:
        return videodesign_service.review(project_id)
    except VideoDesignError as error:
        return error_response(error)


@router.get("/projects/{project_id}/progress")
async def progress(project_id: str):
    try:
        return videodesign_service.progress(project_id)
    except VideoDesignError as error:
        return error_response(error)


@router.patch("/projects/{project_id}/scenes/{scene_id}/selection")
async def select_scene(project_id: str, scene_id: str, request: SceneSelectionRequest):
    try:
        return videodesign_service.select_scene(project_id, scene_id, request)
    except VideoDesignError as error:
        return error_response(error)


@router.post("/projects/{project_id}/materials/download")
async def download_materials(project_id: str, request: MaterialsDownloadRequest):
    try:
        return await videodesign_service.download_materials(project_id, request)
    except VideoDesignError as error:
        return error_response(error)


@router.post("/projects/{project_id}/materials/prune")
async def prune_materials(project_id: str, request: MaterialsPruneRequest):
    try:
        return videodesign_service.prune_material_candidates(project_id, request)
    except VideoDesignError as error:
        return error_response(error)


@router.get("/projects/{project_id}/materials/{asset_id}/file")
async def material_file(project_id: str, asset_id: str):
    try:
        path = Path(videodesign_service.material_file_path(project_id, asset_id))
        if not path.exists():
            raise VideoDesignError("MATERIAL_FILE_NOT_FOUND", "Downloaded material file does not exist.", retryable=True)
        return FileResponse(path, media_type="video/mp4")
    except VideoDesignError as error:
        return error_response(error)


@router.get("/projects/{project_id}/materials/{asset_id}/proxy")
async def material_proxy(project_id: str, asset_id: str):
    try:
        path = Path(videodesign_service.material_proxy_path(project_id, asset_id))
        if not path.exists():
            raise VideoDesignError("MATERIAL_FILE_NOT_FOUND", "Material preview proxy file does not exist.", retryable=True)
        return FileResponse(path, media_type="video/mp4")
    except VideoDesignError as error:
        return error_response(error)


@router.post("/projects/{project_id}/studio")
async def create_studio(project_id: str):
    try:
        return await videodesign_service.create_studio_timeline(project_id)
    except VideoDesignError as error:
        return error_response(error)


@router.get("/projects/{project_id}/timeline")
async def timeline(project_id: str):
    try:
        return videodesign_service.timeline(project_id)
    except VideoDesignError as error:
        return error_response(error)


@router.delete("/projects/{project_id}/timeline")
async def clear_timeline(project_id: str):
    try:
        return videodesign_service.clear_timeline(project_id)
    except VideoDesignError as error:
        return error_response(error)


@router.post("/projects/{project_id}/timeline/items")
async def create_timeline_item(project_id: str, request: TimelineItemCreateRequest):
    try:
        return videodesign_service.create_timeline_item(project_id, request)
    except VideoDesignError as error:
        return error_response(error)


@router.patch("/projects/{project_id}/timeline/items/{item_id}")
async def patch_timeline_item(project_id: str, item_id: str, request: TimelineItemPatch):
    try:
        return videodesign_service.patch_timeline_item(project_id, item_id, request)
    except VideoDesignError as error:
        return error_response(error)


@router.delete("/projects/{project_id}/timeline/items/{item_id}")
async def delete_timeline_item(project_id: str, item_id: str):
    try:
        return videodesign_service.delete_timeline_item(project_id, item_id)
    except VideoDesignError as error:
        return error_response(error)


@router.post("/projects/{project_id}/scenes/{scene_id}/transition")
async def set_scene_transition(project_id: str, scene_id: str, request: TransitionRequest):
    try:
        return videodesign_service.set_scene_transition(project_id, scene_id, request)
    except VideoDesignError as error:
        return error_response(error)


@router.post("/projects/{project_id}/transitions/apply-all")
async def apply_all_transitions(project_id: str, request: TransitionRequest):
    try:
        return videodesign_service.apply_all_transitions(project_id, request)
    except VideoDesignError as error:
        return error_response(error)


@router.post("/projects/{project_id}/transitions/randomize")
async def randomize_transitions(project_id: str):
    try:
        return videodesign_service.randomize_transitions(project_id)
    except VideoDesignError as error:
        return error_response(error)
