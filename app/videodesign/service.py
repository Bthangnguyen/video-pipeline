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
        project = VideoDesignProject(
            project_id=f"vdp_{uuid.uuid4().hex}",
            idea=(request.idea or "").strip(),
            script=(request.script or "").strip(),
            script_source="user" if (request.script or "").strip() else "deepseek_pending",
            target_platform=request.target_platform,
            aspect_ratio=request.aspect_ratio,
            target_duration_seconds=request.target_duration_seconds,
            language=request.language,
            style_brief=request.style_brief,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        self.store.put(project)
        return {"success": True, "project": project.model_dump()}

    def list_projects(self) -> dict:
        projects = sorted(self.store.list(), key=_project_sort_value, reverse=True)
        return {"success": True, "projects": [_project_summary(project) for project in projects]}

    def get_project(self, project_id: str) -> dict:
        project = self.store.get(project_id)
        return {"success": True, "project": project.model_dump()}

    def update_project(self, project_id: str, patch: dict) -> dict:
        project = self.store.get(project_id)
        for key in ("idea", "script", "target_platform", "aspect_ratio", "target_duration_seconds", "language", "style_brief"):
            if key in patch:
                value = patch[key]
                setattr(project, key, value.strip() if isinstance(value, str) else value)
        if "script" in patch:
            project.script_source = "user" if (project.script or "").strip() else "deepseek_pending"
        self.store.put(project)
        return {"success": True, "project": project.model_dump()}

    def set_preset(self, project_id: str, preset: dict) -> dict:
        project = self.store.get(project_id)
        project.design_preset = preset
        self.store.put(project)
        return {"success": True, "project": project.model_dump()}

    def set_split_settings(self, project_id: str, settings_request: SplitSettings) -> dict:
        project = self.store.get(project_id)
        project.split_settings = settings_request
        self.store.put(project)
        return {"success": True, "project": project.model_dump()}

    async def generate_script(self, project_id: str, request: ScriptGenerateRequest) -> dict:
        project = self.store.get(project_id)
        idea = (request.idea or project.idea).strip()
        if not idea:
            raise VideoDesignError(INVALID_PROJECT_INPUT, "Idea is required for DeepSeek script generation.")
        data = await self.script_client.generate(
            idea=idea,
            target_duration_seconds=request.target_duration_seconds or project.target_duration_seconds,
            tone=request.tone or project.style_brief,
            language=request.language or project.language,
        )
        project.idea = idea
        project.script = str(data.get("script") or "")
        project.script_source = "deepseek"
        if data.get("scenes"):
            project.scenes = _scenes_from_deepseek(data["scenes"], project.split_settings)
            _reset_material_search_plan(project)
        self.store.put(project)
        return {"success": True, "project": project.model_dump(), "script_result": data}

    def plan(self, project_id: str) -> dict:
        project = self.store.get(project_id)
        if not project.script.strip():
            raise VideoDesignError(SCRIPT_REQUIRED, "Script is required before planning scenes.")
        project.scenes = split_script(project.script, project.split_settings)
        _reset_material_search_plan(project)
        self.store.put(project)
        return {"success": True, "project_id": project.project_id, "scenes": [scene.model_dump() for scene in project.scenes]}

    def update_scene(self, project_id: str, scene_id: str, patch: dict) -> dict:
        project = self.store.get(project_id)
        scene = _scene(project, scene_id)
        for key in (
            "voiceover_text",
            "tts_text",
            "on_screen_text",
            "caption_text",
            "visual_brief",
            "matching_keywords",
            "negative_keywords",
            "visual_search_plan",
        ):
            if key in patch:
                setattr(scene, key, patch[key])
        if "voiceover_text" in patch and "tts_text" not in patch:
            scene.tts_text = scene.voiceover_text
        self.store.put(project)
        return {"success": True, "scene": scene.model_dump()}

    def update_scene_clip(self, project_id: str, scene_id: str, request: SceneClipPatch) -> dict:
        return self.studio.update_scene_clip(project_id, scene_id, request)

    def split_scene(self, project_id: str, scene_id: str) -> dict:
        project = self.store.get(project_id)
        scene = _scene(project, scene_id)
        words = scene.voiceover_text.split()
        if len(words) < 4:
            raise VideoDesignError(INVALID_PROJECT_INPUT, "Scene is too short to split.")
        midpoint = len(words) // 2
        first = " ".join(words[:midpoint])
        second = " ".join(words[midpoint:])
        index = project.scenes.index(scene)
        replacement = split_script(f"{first}\n{second}", SplitSettings(split_mode="manual", max_words_per_scene=project.split_settings.max_words_per_scene))
        project.scenes[index : index + 1] = replacement
        refresh_scene_orders(project.scenes)
        _reset_material_search_plan(project)
        self.store.put(project)
        return {"success": True, "scenes": [item.model_dump() for item in project.scenes]}

    def merge_scenes(self, project_id: str, scene_ids: list[str]) -> dict:
        project = self.store.get(project_id)
        selected = [scene for scene in project.scenes if scene.scene_id in scene_ids]
        if len(selected) < 2:
            raise VideoDesignError(INVALID_PROJECT_INPUT, "At least two scenes are required to merge.")
        merged_text = " ".join(scene.voiceover_text for scene in selected)
        merged = split_script(merged_text, SplitSettings(split_mode="manual", max_words_per_scene=999))[0]
        first_index = project.scenes.index(selected[0])
        project.scenes = [scene for scene in project.scenes if scene.scene_id not in scene_ids]
        project.scenes.insert(first_index, merged)
        refresh_scene_orders(project.scenes)
        _reset_material_search_plan(project)
        self.store.put(project)
        return {"success": True, "scenes": [item.model_dump() for item in project.scenes]}

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
        project = self.store.get(project_id)
        return {"success": True, "project_id": project.project_id, "progress": project.progress.model_dump()}

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

    def _set_progress(
        self,
        project: VideoDesignProject,
        stage: str,
        message: str,
        current: int,
        total: int,
        detail: dict | None = None,
    ) -> None:
        project.progress.stage = stage
        project.progress.message = message
        project.progress.current = current
        project.progress.total = total
        project.progress.detail = detail or {}
        self.store.put(project)




































































































































































































































def _scenes_from_deepseek(items: list, split_settings: SplitSettings) -> list[ScenePlan]:
    scenes = []
    for index, item in enumerate(items, start=1):
        voiceover = str(item.get("voiceover_text") or item.get("voiceover") or "")
        if not voiceover:
            continue
        duration = estimate_duration(voiceover)
        scenes.append(
            ScenePlan(
                scene_id=f"scn_{uuid.uuid4().hex}",
                order=index,
                voiceover_text=voiceover,
                tts_text=voiceover,
                on_screen_text=str(item.get("on_screen_text") or item.get("headline") or ""),
                caption_text=voiceover,
                caption_chunks=make_caption_chunks(voiceover, duration),
                visual_brief=str(item.get("visual_brief") or voiceover),
                matching_keywords=_normalize_keywords(item.get("search_keywords", []), 1) or _normalize_keywords([voiceover], 1),
                duration_seconds=max(split_settings.min_scene_duration_seconds, min(split_settings.max_scene_duration_seconds, duration)),
                template_scene_id="auto",
            )
        )
    return refresh_scene_orders(scenes)


videodesign_service = VideoDesignService()
