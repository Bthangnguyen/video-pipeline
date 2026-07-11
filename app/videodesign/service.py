import asyncio
import json
import math
import re
import shutil
import wave
import uuid
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

from app.douyinsearch.config import settings as douyin_settings
from app.douyinsearch.cookies import cookie_header_from_file as douyin_cookie_header_from_file
from app.douyinsearch.errors import DouyinSearchError
from app.douyinsearch.schemas import SearchRequest
from app.douyinsearch.stream_proxy import no_watermark_url_from_result
from app.douyinsearch.service import douyin_service
from app.pinterestsearch.config import settings as pinterest_settings
from app.pinterestsearch.cookies import cookie_header_from_file as pinterest_cookie_header_from_file
from app.pinterestsearch.errors import PinterestSearchError
from app.pinterestsearch.schemas import SearchRequest as PinterestSearchRequest
from app.pinterestsearch.service import pinterest_service
from app.videodesign.audio import concatenate_audio_files, measure_audio_duration
from app.videodesign.config import settings
from app.videodesign.downloader import YtDlpDownloader
from app.videodesign.errors import (
    AUDIO_COMBINE_FAILED,
    AUDIO_NOT_FOUND,
    CANDIDATE_NOT_FOUND,
    DOWNLOAD_FAILED,
    INVALID_PROJECT_INPUT,
    MATERIAL_SEARCH_FAILED,
    MATERIAL_SEARCH_TIMEOUT,
    PREVIEW_RENDER_FAILED,
    SCENE_NOT_FOUND,
    SCENE_NOT_READY,
    SCRIPT_GENERATION_FAILED,
    SCRIPT_REQUIRED,
    VideoDesignError,
)
from app.videodesign.materials.candidates import (
    _add_group_candidates,
    _approved_candidate_for_scene,
    _asset,
    _candidate,
    _candidates_for_scene,
    _cookie_file_for_source,
    _cookie_header_for_source,
    _download_source_url,
    _is_blob_url,
    _is_http_url,
    _material_asset_from_candidate,
    _material_output_path,
    _recover_candidate_for_existing_material,
    _recover_existing_material_asset,
    _search_errors_for_scene,
    source_label,
)
from app.videodesign.materials.proxy import _create_preview_proxy as _create_preview_proxy_impl, _proxy_resolution
from app.videodesign.materials.search_plan import (
    _append_keyword,
    _ensure_material_search_plan,
    _fallback_keywords_for_scene,
    _fallback_material_search_group,
    _fallback_material_search_plan,
    _fallback_visual_search_plan,
    _fallback_visual_search_plan_from_keywords,
    _fallbacks_for_source,
    _first_text,
    _generated_search_group_is_grounded,
    _keywords_for_search_group,
    _legacy_keywords_from_visual_plan,
    _material_search_plan_from_scene_plans,
    _merge_generated_material_search_plan,
    _normalize_douyin_visual_query,
    _normalize_generated_material_search_plan,
    _normalize_keywords,
    _normalize_pinterest_visual_query,
    _normalize_user_material_search_plan,
    _normalize_user_material_search_plan_for_scenes,
    _normalize_visual_search_plan,
    _project_base_keyword,
    _reset_material_search_plan,
    _search_groups_for_request,
    _should_translate_douyin_keyword,
    _sync_scene_group_ids,
    _sync_scenes_from_material_search_plan,
    _unique_search_group_id,
    _visual_grounding_tokens,
    _visual_plan_is_grounded,
)
from app.videodesign.materials.service import MaterialsService
from app.videodesign.planner import estimate_duration, make_caption_chunks, refresh_scene_orders, split_script
from app.videodesign.project_service import ProjectService
from app.videodesign.project_state import (
    _delete_project_file,
    _mark_preview_stale,
    _project_sort_value,
    _project_summary,
    _project_title,
    _renderable_scenes,
    _reset_smooth_preview,
    _scene,
    _selected_scenes,
)
from app.videodesign.schemas import (
    CreateProjectRequest,
    DouyinSearchTask,
    KeywordGenerateRequest,
    MaterialsDownloadRequest,
    MaterialsPreflightRequest,
    MaterialsPruneRequest,
    MaterialsSearchRequest,
    MaterialAsset,
    MediaCandidate,
    MaterialSearchGroup,
    MaterialSearchPlan,
    SceneClip,
    SceneClipPatch,
    SceneAudioOffset,
    ScenePlan,
    SceneSelectionRequest,
    SFXApplyRequest,
    SFXAsset,
    SFXSuggestRequest,
    SFXSuggestion,
    ScriptGenerateRequest,
    SplitSettings,
    SmoothPreview,
    TTSGenerateRequest,
    TTSMeta,
    TTSSettings,
    TimelineDraft,
    TimelineItemCreateRequest,
    TimelineItem,
    TimelineItemPatch,
    TransitionRequest,
    VideoDesignProject,
    VoiceoverTrack,
)
from app.videodesign.script_client import DeepSeekScriptClient
from app.videodesign.store import VideoDesignStore
from app.videodesign.studio.constants import TIMELINE_MIN_ITEM_DURATION
from app.videodesign.studio.render import RenderService, _render_smooth_preview_file as _render_smooth_preview_file_impl
from app.videodesign.studio.service import StudioService
from app.videodesign.studio.sfx import SFXService
from app.videodesign.tts import TTSClient
from app.videodesign.voiceover_service import VoiceoverService






async def _create_preview_proxy(asset: MaterialAsset, aspect_ratio: str) -> Path | None:
    return await _create_preview_proxy_impl(asset, aspect_ratio)


async def _ensure_preview_proxy(asset: MaterialAsset, aspect_ratio: str) -> Path | None:
    if asset.proxy_path and Path(asset.proxy_path).exists():
        return Path(asset.proxy_path)
    proxy_path = await _create_preview_proxy(asset, aspect_ratio)
    if proxy_path:
        asset.proxy_path = str(proxy_path)
    return proxy_path


async def _render_smooth_preview_file(project: VideoDesignProject) -> Path:
    return await _render_smooth_preview_file_impl(project)


class VideoDesignService:
    def __init__(self):
        self.store = VideoDesignStore()
        self.script_client = DeepSeekScriptClient()
        self.tts_client = TTSClient()
        self.ytdlp = YtDlpDownloader()
        self.projects = ProjectService(self.store, self.script_client)
        self.materials = MaterialsService(self.store, self.script_client, self.ytdlp)
        self.voiceover = VoiceoverService(self.store, self.tts_client)
        self.sfx = SFXService(self.store)
        self.render = RenderService(self.store)
        self.studio = StudioService(self.store)

    def health(self) -> dict:
        return {
            "success": True,
            "module": "videodesign",
            "storage_dir": str(settings.storage_dir),
            "deepseek_configured": bool(settings.deepseek_api_key),
            "tts_provider": settings.tts_provider,
            "redis_enabled": self.store.redis.enabled,
        }

    def create_project(self, request: CreateProjectRequest) -> dict:
        return self.projects.create_project(request)

    def list_projects(self) -> dict:
        return self.projects.list_projects()

    def get_project(self, project_id: str) -> dict:
        return self.projects.get_project(project_id)

    def update_project(self, project_id: str, patch: dict) -> dict:
        return self.projects.update_project(project_id, patch)

    def set_preset(self, project_id: str, preset: dict) -> dict:
        return self.projects.set_preset(project_id, preset)

    def set_split_settings(self, project_id: str, settings_request: SplitSettings) -> dict:
        return self.projects.set_split_settings(project_id, settings_request)

    async def generate_script(self, project_id: str, request: ScriptGenerateRequest) -> dict:
        return await self.projects.generate_script(project_id, request)

    def plan(self, project_id: str) -> dict:
        return self.projects.plan(project_id)

    def update_scene(self, project_id: str, scene_id: str, patch: dict) -> dict:
        return self.projects.update_scene(project_id, scene_id, patch)

    def update_scene_clip(self, project_id: str, scene_id: str, request: SceneClipPatch) -> dict:
        return self.studio.update_scene_clip(project_id, scene_id, request)

    def split_scene(self, project_id: str, scene_id: str) -> dict:
        return self.projects.split_scene(project_id, scene_id)

    def merge_scenes(self, project_id: str, scene_ids: list[str]) -> dict:
        return self.projects.merge_scenes(project_id, scene_ids)

    async def generate_tts(self, project_id: str, request: TTSGenerateRequest) -> dict:
        return await self.voiceover.generate_tts(project_id, request)


    def clear_tts(self, project_id: str) -> dict:
        return self.voiceover.clear_tts(project_id)

    def build_combined_voiceover(self, project_id: str) -> dict:
        return self.voiceover.build_combined_voiceover(project_id)

    def combined_voiceover_path(self, project_id: str) -> Path:
        return self.voiceover.combined_voiceover_path(project_id)

    async def generate_scene_keywords(self, project_id: str, request: KeywordGenerateRequest) -> dict:
        return await self.materials.generate_scene_keywords(project_id, request)

    def set_material_search_plan(self, project_id: str, request: MaterialSearchPlan) -> dict:
        return self.materials.set_material_search_plan(project_id, request)

    async def search_materials(self, project_id: str, request: MaterialsSearchRequest) -> dict:
        return await self.materials.search_materials(project_id, request)

    async def materials_preflight(self, request: MaterialsPreflightRequest) -> dict:
        return await self.materials.materials_preflight(request)


    def review(self, project_id: str) -> dict:
        return self.materials.review(project_id)

    def progress(self, project_id: str) -> dict:
        return self.projects.progress(project_id)

    def select_scene(self, project_id: str, scene_id: str, request: SceneSelectionRequest) -> dict:
        return self.materials.select_scene(project_id, scene_id, request)

    async def download_materials(self, project_id: str, request: MaterialsDownloadRequest) -> dict:
        self.materials.download_candidate = self._download_candidate
        self.materials.ensure_preview_proxy = _ensure_preview_proxy
        return await self.materials.download_materials(project_id, request)

    async def _download_candidate(self, candidate: MediaCandidate, output_path: Path) -> None:
        await self.materials._download_candidate_impl(candidate, output_path)

    def prune_material_candidates(self, project_id: str, request: MaterialsPruneRequest) -> dict:
        return self.materials.prune_material_candidates(project_id, request)



    async def create_studio_timeline(self, project_id: str) -> dict:
        self.studio.ensure_preview_proxy = _ensure_preview_proxy
        return await self.studio.create_studio_timeline(project_id)

    def timeline(self, project_id: str) -> dict:
        return self.studio.timeline(project_id)

    def clear_timeline(self, project_id: str) -> dict:
        return self.studio.clear_timeline(project_id)

    def preview_status(self, project_id: str) -> dict:
        return self.render.preview_status(project_id)

    async def render_smooth_preview(self, project_id: str) -> dict:
        self.render.render_preview_file = _render_smooth_preview_file
        return await self.render.render_smooth_preview(project_id)

    async def render_export(self, project_id: str) -> dict:
        return await self.render.render_export(project_id)

    def export_file_path(self, project_id: str) -> Path:
        return self.render.export_file_path(project_id)

    def export_filename(self, project_id: str) -> str:
        return self.render.export_filename(project_id)

    def smooth_preview_file_path(self, project_id: str) -> Path:
        return self.render.smooth_preview_file_path(project_id)

    def material_file_path(self, project_id: str, asset_id: str) -> str:
        return self.materials.material_file_path(project_id, asset_id)

    def material_proxy_path(self, project_id: str, asset_id: str) -> str:
        return self.materials.material_proxy_path(project_id, asset_id)

    def upload_background_music(self, project_id: str, filename: str, content: bytes, content_type: str = "") -> dict:
        return self.studio.upload_background_music(project_id, filename, content, content_type)

    def background_music_file_path(self, project_id: str, item_id: str) -> Path:
        return self.studio.background_music_file_path(project_id, item_id)

    def create_timeline_item(self, project_id: str, request: TimelineItemCreateRequest) -> dict:
        return self.studio.create_timeline_item(project_id, request)

    def patch_timeline_item(self, project_id: str, item_id: str, patch: TimelineItemPatch) -> dict:
        return self.studio.patch_timeline_item(project_id, item_id, patch)

    def delete_timeline_item(self, project_id: str, item_id: str) -> dict:
        return self.studio.delete_timeline_item(project_id, item_id)

    def set_scene_transition(self, project_id: str, scene_id: str, request: TransitionRequest) -> dict:
        return self.studio.set_scene_transition(project_id, scene_id, request)

    def apply_all_transitions(self, project_id: str, request: TransitionRequest) -> dict:
        return self.studio.apply_all_transitions(project_id, request)

    def randomize_transitions(self, project_id: str) -> dict:
        return self.studio.randomize_transitions(project_id)

    def sfx_catalog(self) -> dict:
        return self.sfx.sfx_catalog()

    def sfx_file_path(self, asset_id: str) -> Path:
        return self.sfx.sfx_file_path(asset_id)

    def suggest_sfx(self, project_id: str, request: SFXSuggestRequest) -> dict:
        return self.sfx.suggest_sfx(project_id, request)

    def sfx_suggestions(self, project_id: str) -> dict:
        return self.sfx.sfx_suggestions(project_id)

    def apply_sfx_suggestions(self, project_id: str, request: SFXApplyRequest) -> dict:
        return self.sfx.apply_sfx_suggestions(project_id, request)







































































































































































































































videodesign_service = VideoDesignService()
