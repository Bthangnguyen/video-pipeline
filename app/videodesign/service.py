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
from app.videodesign.project_state import _scene, _selected_scenes
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
from app.videodesign.tts import TTSClient




TIMELINE_MIN_ITEM_DURATION = 0.25
SFX_SAMPLE_RATE = 44100
STATIC_SFX_ROOT = Path(__file__).resolve().parents[1] / "static" / "sfx" / "mixkit"
STATIC_SFX_RECOMMENDED_EVENTS = {
    "pop": ["caption_word", "text_overlay"],
    "click": ["icon", "text_overlay"],
    "whoosh": ["transition", "icon"],
    "impact": ["hook", "transition", "caption_word"],
    "ding": ["icon", "caption_word"],
    "glitch": ["transition", "text_overlay"],
}
STATIC_SFX_DEFAULT_VOLUME = {
    "pop": 0.28,
    "click": 0.22,
    "whoosh": 0.32,
    "impact": 0.34,
    "ding": 0.24,
    "glitch": 0.22,
}
SFX_TRANSITION_PRESETS = {
    "none": {"enabled": False, "category": "none", "volume": 0.0, "duration_seconds": 0.0},
    "clean_cut": {"enabled": False, "category": "none", "volume": 0.0, "duration_seconds": 0.0},
    "fade": {
        "enabled": True,
        "category": "whoosh",
        "asset_ids": ["mixkit_whoosh_air_woosh"],
        "volume": 0.12,
        "duration_seconds": 0.45,
    },
    "dissolve": {
        "enabled": True,
        "category": "whoosh",
        "asset_ids": ["mixkit_whoosh_air_woosh"],
        "volume": 0.1,
        "duration_seconds": 0.45,
    },
    "slide_left": {
        "enabled": True,
        "category": "whoosh",
        "asset_ids": ["mixkit_whoosh_fast_whoosh_transition"],
        "volume": 0.26,
        "duration_seconds": 0.38,
    },
    "slide_right": {
        "enabled": True,
        "category": "whoosh",
        "asset_ids": ["mixkit_whoosh_fast_whoosh_transition"],
        "volume": 0.26,
        "duration_seconds": 0.38,
    },
    "slide_up": {
        "enabled": True,
        "category": "whoosh",
        "asset_ids": ["mixkit_whoosh_fast_rocket_whoosh"],
        "volume": 0.24,
        "duration_seconds": 0.4,
    },
    "push_slide": {
        "enabled": True,
        "category": "whoosh",
        "asset_ids": ["mixkit_whoosh_cinematic_whoosh_fast_transition"],
        "volume": 0.28,
        "duration_seconds": 0.42,
    },
    "whip_pan": {
        "enabled": True,
        "category": "whoosh",
        "asset_ids": ["mixkit_whoosh_cinematic_whoosh_fast_transition"],
        "volume": 0.34,
        "duration_seconds": 0.32,
    },
    "zoom_in": {
        "enabled": True,
        "category": "impact",
        "asset_ids": ["mixkit_impact_quick_zoom_impact"],
        "volume": 0.25,
        "duration_seconds": 0.32,
    },
    "zoom_out": {
        "enabled": True,
        "category": "impact",
        "asset_ids": ["mixkit_impact_quick_zoom_impact"],
        "volume": 0.23,
        "duration_seconds": 0.32,
    },
    "flash_cut": {
        "enabled": True,
        "category": "glitch",
        "asset_ids": ["mixkit_glitch_small_electric_glitch"],
        "volume": 0.22,
        "duration_seconds": 0.24,
    },
    "speed_zoom": {
        "enabled": True,
        "category": "impact",
        "asset_ids": ["mixkit_impact_cinematic_whoosh_deep_impact"],
        "volume": 0.3,
        "duration_seconds": 0.35,
    },
    "fast_swipes": {
        "enabled": True,
        "category": "whoosh",
        "asset_ids": ["mixkit_whoosh_cinematic_whoosh_fast_transition"],
        "volume": 0.3,
        "duration_seconds": 0.35,
    },
}
LEGACY_SFX_DEFS = [
    {
        "asset_id": "sfx_pop_soft",
        "name": "Soft Pop",
        "category": "caption",
        "duration_seconds": 0.24,
        "frequency": 660,
        "default_volume": 0.32,
        "recommended_events": ["caption_word", "text_overlay", "icon"],
    },
    {
        "asset_id": "sfx_click_soft",
        "name": "Soft Click",
        "category": "icon",
        "duration_seconds": 0.18,
        "frequency": 1100,
        "default_volume": 0.24,
        "recommended_events": ["icon", "text_overlay"],
    },
    {
        "asset_id": "sfx_whoosh_short",
        "name": "Short Whoosh",
        "category": "transition",
        "duration_seconds": 0.42,
        "frequency": 320,
        "sweep_to": 880,
        "default_volume": 0.34,
        "recommended_events": ["transition", "icon"],
    },
    {
        "asset_id": "sfx_impact_soft",
        "name": "Soft Impact",
        "category": "hook",
        "duration_seconds": 0.38,
        "frequency": 150,
        "default_volume": 0.38,
        "recommended_events": ["hook", "transition", "caption_word"],
    },
    {
        "asset_id": "sfx_ding",
        "name": "Ding",
        "category": "emphasis",
        "duration_seconds": 0.34,
        "frequency": 880,
        "sweep_to": 1320,
        "default_volume": 0.28,
        "recommended_events": ["icon", "caption_word"],
    },
]


async def _create_preview_proxy(asset: MaterialAsset, aspect_ratio: str) -> Path | None:
    return await _create_preview_proxy_impl(asset, aspect_ratio)


async def _ensure_preview_proxy(asset: MaterialAsset, aspect_ratio: str) -> Path | None:
    if asset.proxy_path and Path(asset.proxy_path).exists():
        return Path(asset.proxy_path)
    proxy_path = await _create_preview_proxy(asset, aspect_ratio)
    if proxy_path:
        asset.proxy_path = str(proxy_path)
    return proxy_path


class VideoDesignService:
    def __init__(self):
        self.store = VideoDesignStore()
        self.script_client = DeepSeekScriptClient()
        self.tts_client = TTSClient()
        self.ytdlp = YtDlpDownloader()
        self.materials = MaterialsService(self.store, self.script_client, self.ytdlp)

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
        project = self.store.get(project_id)
        scene = _scene(project, scene_id)
        asset_id = request.material_asset_id or scene.material_asset_id
        if not asset_id:
            raise VideoDesignError(SCENE_NOT_READY, "Scene must have downloaded material before selecting a clip.")
        asset = _asset(project, asset_id)
        if asset.scene_id != scene.scene_id:
            raise VideoDesignError(SCENE_NOT_READY, "Material asset does not belong to this scene.")
        if request.asset_duration_seconds is not None:
            asset.duration = round(float(request.asset_duration_seconds), 2)
        duration = _scene_duration(scene)
        scene.clip = _make_scene_clip(scene, asset, duration, request)
        _sync_scene_clip_to_timeline(project, scene, asset)
        _mark_preview_stale(project)
        self.store.put(project)
        return {"success": True, "scene": scene.model_dump(), "timeline": project.timeline.model_dump() if project.timeline else None}

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
        project = self.store.get(project_id)
        provider = request.provider or project.tts_settings.provider
        voice_id = request.voice_id or project.tts_settings.voice_id
        voice_speed = float(request.voice_speed or project.tts_settings.voice_speed or 1)
        if not request.scene_ids:
            return await self._generate_global_tts(project, provider, voice_id, voice_speed)
        scenes = _selected_scenes(project, request.scene_ids)
        for scene in scenes:
            text = scene.tts_text or scene.voiceover_text
            _delete_project_file(project, scene.tts.audio_path)
            result = await self.tts_client.generate(text, project.project_id, scene.scene_id, provider, voice_id, voice_speed)
            previous_duration = scene.duration_seconds
            scene.duration_seconds = result.duration_seconds
            if scene.clip and previous_duration and abs(scene.clip.duration_seconds - result.duration_seconds) > 0.05:
                scene.clip.status = "trim_stale"
            scene.caption_chunks = result.caption_chunks
            scene.tts = TTSMeta(
                provider=provider,
                voice_id=voice_id,
                audio_url=f"/api/videodesign/projects/{project.project_id}/scenes/{scene.scene_id}/audio",
                audio_path=str(result.audio_path),
                duration_seconds=result.duration_seconds,
                sync_state="synced",
            )
        project.tts_settings = TTSSettings(language=project.language, provider=provider, voice_id=voice_id, voice_speed=voice_speed)
        _delete_project_file(project, project.voiceover_track.audio_path)
        project.voiceover_track = VoiceoverTrack()
        self.store.put(project)
        return {"success": True, "project": project.model_dump(), "scenes": [scene.model_dump() for scene in scenes]}

    async def _generate_global_tts(self, project: VideoDesignProject, provider: str, voice_id: str, voice_speed: float) -> dict:
        scenes = _renderable_scenes(project)
        if not scenes:
            raise VideoDesignError(SCENE_NOT_READY, "Project has no scenes for TTS.")
        for scene in project.scenes:
            _delete_project_file(project, scene.tts.audio_path)
            scene.tts = TTSMeta()
        _delete_project_file(project, project.voiceover_track.audio_path)

        scene_texts = [scene.tts_text or scene.voiceover_text for scene in scenes]
        full_text = " ".join(text.strip() for text in scene_texts if text.strip()).strip()
        if not full_text:
            raise VideoDesignError(SCRIPT_REQUIRED, "No scene voiceover text is available for TTS.")

        result = await self.tts_client.generate(full_text, project.project_id, "global_voiceover", provider, voice_id, voice_speed)
        offsets = _assign_global_tts_offsets(scenes, result.duration_seconds)
        for scene, offset in zip(scenes, offsets):
            duration = round(max(0.05, offset.end_seconds - offset.start_seconds), 3)
            previous_duration = scene.duration_seconds
            scene.duration_seconds = duration
            if scene.clip and previous_duration and abs(scene.clip.duration_seconds - duration) > 0.05:
                scene.clip.status = "trim_stale"
            text = scene.caption_text or scene.tts_text or scene.voiceover_text
            scene.caption_chunks = make_caption_chunks(text, duration)
            scene.tts = TTSMeta(
                provider=provider,
                voice_id=voice_id,
                duration_seconds=duration,
                sync_state="synced",
            )

        project.voiceover_track = VoiceoverTrack(
            audio_url=f"/api/videodesign/projects/{project.project_id}/audio/combined",
            audio_path=str(result.audio_path),
            duration_seconds=round(result.duration_seconds, 3),
            scene_offsets=offsets,
        )
        project.tts_settings = TTSSettings(language=project.language, provider=provider, voice_id=voice_id, voice_speed=voice_speed)
        project.timeline = None
        _reset_smooth_preview(project)
        self.store.put(project)
        return {
            "success": True,
            "project": project.model_dump(),
            "voiceover_track": project.voiceover_track.model_dump(),
            "scenes": [scene.model_dump() for scene in scenes],
        }

    def clear_tts(self, project_id: str) -> dict:
        project = self.store.get(project_id)
        deleted = 0
        for scene in project.scenes:
            if _delete_project_file(project, scene.tts.audio_path):
                deleted += 1
            text = scene.tts_text or scene.voiceover_text
            scene.tts = TTSMeta()
            scene.caption_chunks = make_caption_chunks(text, estimate_duration(text))
            scene.duration_seconds = estimate_duration(text)
            if scene.clip:
                scene.clip.status = "trim_stale"
        if _delete_project_file(project, project.voiceover_track.audio_path):
            deleted += 1
        project.voiceover_track = VoiceoverTrack()
        project.timeline = None
        _reset_smooth_preview(project)
        self.store.put(project)
        return {
            "success": True,
            "deleted_files": deleted,
            "project": project.model_dump(),
            "scenes": [scene.model_dump() for scene in project.scenes],
        }

    def build_combined_voiceover(self, project_id: str) -> dict:
        project = self.store.get(project_id)
        if project.voiceover_track.audio_path and Path(project.voiceover_track.audio_path).exists():
            return {"success": True, "voiceover_track": project.voiceover_track.model_dump()}
        scenes = _renderable_scenes(project)
        if not scenes:
            raise VideoDesignError(SCENE_NOT_READY, "Project has no renderable scenes.")

        audio_paths: list[Path] = []
        offsets: list[SceneAudioOffset] = []
        current = 0.0
        for scene in scenes:
            if not scene.tts.audio_path:
                raise VideoDesignError(AUDIO_NOT_FOUND, f"Scene {scene.scene_id} has no generated TTS audio.")
            audio_path = Path(scene.tts.audio_path)
            if not audio_path.exists():
                raise VideoDesignError(AUDIO_NOT_FOUND, f"Scene audio file does not exist: {scene.scene_id}.")
            duration = measure_audio_duration(audio_path) or scene.tts.duration_seconds or scene.duration_seconds
            if duration <= 0:
                raise VideoDesignError(AUDIO_NOT_FOUND, f"Could not measure scene audio duration: {scene.scene_id}.")
            scene.duration_seconds = duration
            scene.tts.duration_seconds = duration
            scene.caption_chunks = make_caption_chunks(scene.caption_text or scene.tts_text or scene.voiceover_text, duration)
            start = current
            current = round(current + duration, 3)
            offsets.append(
                SceneAudioOffset(
                    scene_id=scene.scene_id,
                    start_seconds=round(start, 3),
                    end_seconds=current,
                )
            )
            audio_paths.append(audio_path)

        output_dir = settings.storage_dir / project.project_id / "audio"
        try:
            combined_path, combined_duration = concatenate_audio_files(audio_paths, output_dir)
        except ValueError as exc:
            raise VideoDesignError(AUDIO_COMBINE_FAILED, f"Could not combine scene audio: {exc}", retryable=True) from exc

        if combined_duration <= 0:
            combined_duration = current
        project.voiceover_track = VoiceoverTrack(
            audio_url=f"/api/videodesign/projects/{project.project_id}/audio/combined",
            audio_path=str(combined_path),
            duration_seconds=round(combined_duration, 3),
            scene_offsets=offsets,
        )
        if project.timeline:
            project.timeline.duration_seconds = round(combined_duration, 3)
            _mark_preview_stale(project)
        self.store.put(project)
        return {"success": True, "voiceover_track": project.voiceover_track.model_dump()}

    def combined_voiceover_path(self, project_id: str) -> Path:
        project = self.store.get(project_id)
        if not project.voiceover_track.audio_path:
            raise VideoDesignError(AUDIO_NOT_FOUND, "Combined voiceover has not been created.")
        path = Path(project.voiceover_track.audio_path)
        if not path.exists():
            raise VideoDesignError(AUDIO_NOT_FOUND, "Combined voiceover file does not exist.", retryable=True)
        return path

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
        project = self.store.get(project_id)
        items: list[TimelineItem] = []
        current = 0.0
        renderable_scenes = _renderable_scenes(project)
        voiceover_offsets = {offset.scene_id: offset for offset in project.voiceover_track.scene_offsets}
        for index, scene in enumerate(renderable_scenes):
            if scene.approval_state == "placeholder_allowed":
                continue
            if not scene.material_asset_id:
                raise VideoDesignError(SCENE_NOT_READY, f"Scene {scene.scene_id} must be downloaded before studio.")
            asset = _asset(project, scene.material_asset_id)
            await _ensure_preview_proxy(asset, project.aspect_ratio)
            offset = voiceover_offsets.get(scene.scene_id)
            if offset:
                start = round(offset.start_seconds, 2)
                end = round(max(start + 0.25, offset.end_seconds), 2)
                duration = round(end - start, 2)
            else:
                start = current
                duration = _scene_duration(scene)
                end = round(current + duration, 2)
            if not scene.clip or scene.clip.material_asset_id != asset.asset_id:
                scene.clip = _make_scene_clip(scene, asset, duration)
            _apply_video_defaults_to_clip(scene.clip, project.design_preset)
            items.extend(_timeline_items_for_scene(project.project_id, scene, asset, start, end, project.design_preset))
            if index < len(renderable_scenes) - 1:
                items.append(_transition_item_for_scene(scene, end, project.design_preset))
            current = max(current, end)
        timeline_duration = project.voiceover_track.duration_seconds or current
        timeline = TimelineDraft(
            timeline_id=f"tln_{uuid.uuid4().hex}",
            project_id=project.project_id,
            duration_seconds=round(timeline_duration, 2),
            aspect_ratio=project.aspect_ratio,
            scenes=[scene.scene_id for scene in project.scenes],
            layers=["media_base", "overlay_default", "caption_default", "text_overlay", "icon", "voiceover_audio", "background_audio", "transition_out", "sfx"],
            items=items,
        )
        project.timeline = timeline
        _mark_preview_stale(project)
        self.store.put(project)
        return {"success": True, "timeline": timeline.model_dump()}

    def timeline(self, project_id: str) -> dict:
        project = self.store.get(project_id)
        return {"success": True, "timeline": project.timeline.model_dump() if project.timeline else None}

    def clear_timeline(self, project_id: str) -> dict:
        project = self.store.get(project_id)
        project.timeline = None
        _reset_smooth_preview(project)
        self.store.put(project)
        return {"success": True, "project_id": project.project_id, "timeline": None}

    def preview_status(self, project_id: str) -> dict:
        project = self.store.get(project_id)
        return {"success": True, "preview": project.smooth_preview.model_dump()}

    async def render_smooth_preview(self, project_id: str) -> dict:
        project = self.store.get(project_id)
        if not project.timeline:
            raise VideoDesignError(SCENE_NOT_READY, "Timeline has not been created.")
        project.smooth_preview.status = "rendering"
        project.smooth_preview.error = {}
        self.store.put(project)
        try:
            path = await _render_smooth_preview_file(project)
        except VideoDesignError as error:
            project.smooth_preview.status = "failed"
            project.smooth_preview.error = error.to_payload()
            self.store.put(project)
            raise
        except Exception as exc:
            error = VideoDesignError(PREVIEW_RENDER_FAILED, f"Could not render smooth preview: {exc}", retryable=True)
            project.smooth_preview.status = "failed"
            project.smooth_preview.error = error.to_payload()
            self.store.put(project)
            raise error from exc

        updated_at = datetime.now(timezone.utc).isoformat()
        project.smooth_preview = SmoothPreview(
            status="ready",
            preview_url=_smooth_preview_url(project.project_id, updated_at),
            preview_path=str(path),
            timeline_id=project.timeline.timeline_id,
            duration_seconds=project.timeline.duration_seconds,
            updated_at=updated_at,
        )
        self.store.put(project)
        return {"success": True, "preview": project.smooth_preview.model_dump()}

    async def render_export(self, project_id: str) -> dict:
        result = await self.render_smooth_preview(project_id)
        return {
            "success": True,
            "preview": result["preview"],
            "export_url": _export_url(project_id),
        }

    def export_file_path(self, project_id: str) -> Path:
        project = self.store.get(project_id)
        if project.smooth_preview.status != "ready" or not project.smooth_preview.preview_path:
            raise VideoDesignError(PREVIEW_RENDER_FAILED, "Render the export before downloading the MP4.", retryable=True)
        path = Path(project.smooth_preview.preview_path)
        if not path.exists():
            raise VideoDesignError(PREVIEW_RENDER_FAILED, "Rendered export file does not exist.", retryable=True)
        return path

    def export_filename(self, project_id: str) -> str:
        project = self.store.get(project_id)
        title = _project_title(project)
        return f"{_safe_filename(title)}.mp4"

    def smooth_preview_file_path(self, project_id: str) -> Path:
        project = self.store.get(project_id)
        if project.smooth_preview.status not in {"ready", "stale"} or not project.smooth_preview.preview_path:
            raise VideoDesignError(PREVIEW_RENDER_FAILED, "Smooth preview has not been rendered yet.", retryable=True)
        path = Path(project.smooth_preview.preview_path)
        if not path.exists():
            raise VideoDesignError(PREVIEW_RENDER_FAILED, "Smooth preview file does not exist.", retryable=True)
        return path

    def material_file_path(self, project_id: str, asset_id: str) -> str:
        return self.materials.material_file_path(project_id, asset_id)

    def material_proxy_path(self, project_id: str, asset_id: str) -> str:
        return self.materials.material_proxy_path(project_id, asset_id)

    def upload_background_music(self, project_id: str, filename: str, content: bytes, content_type: str = "") -> dict:
        project = self.store.get(project_id)
        if not project.timeline:
            raise VideoDesignError(SCENE_NOT_READY, "Timeline has not been created.")
        if not content:
            raise VideoDesignError(INVALID_PROJECT_INPUT, "Music file is empty.")
        suffix = Path(filename or "").suffix.lower()
        allowed_suffixes = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"}
        if suffix not in allowed_suffixes and not str(content_type or "").startswith("audio/"):
            raise VideoDesignError(INVALID_PROJECT_INPUT, "Upload an audio file for background music.")
        if suffix not in allowed_suffixes:
            suffix = ".mp3"
        music_dir = settings.storage_dir / project.project_id / "music"
        music_dir.mkdir(parents=True, exist_ok=True)
        item_id = f"itm_{uuid.uuid4().hex}"
        safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "-", Path(filename or "background-music").stem).strip("-") or "background-music"
        output_path = music_dir / f"{item_id}-{safe_name}{suffix}"
        output_path.write_bytes(content)
        try:
            duration_seconds = measure_audio_duration(output_path)
        except Exception as exc:
            _delete_project_file(project, str(output_path))
            raise VideoDesignError(INVALID_PROJECT_INPUT, f"Could not read uploaded music: {exc}") from exc

        for old_item in [item for item in project.timeline.items if item.type == "music"]:
            _delete_project_file(project, str(old_item.source_ref.get("local_path") or ""))
        project.timeline.items = [item for item in project.timeline.items if item.type != "music"]
        scene_id = project.timeline.scenes[0] if project.timeline.scenes else project.scenes[0].scene_id
        duration = max(0.25, float(project.timeline.duration_seconds or duration_seconds or 0.25))
        item = TimelineItem(
            item_id=item_id,
            layer_id="background_audio",
            scene_id=scene_id,
            type="music",
            start_seconds=0,
            end_seconds=round(duration, 3),
            source_ref={
                "name": Path(filename or "Background music").name,
                "local_path": str(output_path),
                "audio_url": f"/api/videodesign/projects/{project.project_id}/music/{item_id}/file",
                "duration_seconds": round(float(duration_seconds or 0), 3),
                "trim_start_seconds": 0,
                "trim_end_seconds": round(float(duration_seconds or 0), 3),
            },
            style={
                "enabled": True,
                "volume": 0.16,
                "ducking": True,
                "ducking_volume": 0.08,
                "fade_in_seconds": 1.0,
                "fade_out_seconds": 1.0,
                "loop": True,
            },
        )
        if "background_audio" not in project.timeline.layers:
            project.timeline.layers.append("background_audio")
        project.timeline.items.append(item)
        _mark_preview_stale(project)
        self.store.put(project)
        return {"success": True, "item": item.model_dump(), "timeline": project.timeline.model_dump()}

    def background_music_file_path(self, project_id: str, item_id: str) -> Path:
        project = self.store.get(project_id)
        if not project.timeline:
            raise VideoDesignError(SCENE_NOT_READY, "Timeline has not been created.")
        item = next((entry for entry in project.timeline.items if entry.item_id == item_id and entry.type == "music"), None)
        if not item:
            raise VideoDesignError(SCENE_NOT_FOUND, "Background music item does not exist.")
        path = Path(str(item.source_ref.get("local_path") or ""))
        if not path.exists():
            raise VideoDesignError(AUDIO_NOT_FOUND, "Background music file does not exist.", retryable=True)
        return path

    def create_timeline_item(self, project_id: str, request: TimelineItemCreateRequest) -> dict:
        project = self.store.get(project_id)
        if not project.timeline:
            raise VideoDesignError(SCENE_NOT_READY, "Timeline has not been created.")
        _scene(project, request.scene_id)
        bounds = _scene_timeline_bounds(project, request.scene_id)
        start = request.start_seconds if request.start_seconds is not None else bounds[0]
        end = request.end_seconds if request.end_seconds is not None else _default_end_for_item_type(request.type, start, bounds)
        start, end = _clamp_item_bounds(start, end, bounds)
        layer_id = request.layer_id or _default_layer_for_item_type(request.type)
        item = TimelineItem(
            item_id=f"itm_{uuid.uuid4().hex}",
            layer_id=layer_id,
            scene_id=request.scene_id,
            type=request.type,
            start_seconds=start,
            end_seconds=end,
            source_ref=request.source_ref,
            transform=request.transform or _default_transform_for_item_type(request.type),
            style=request.style,
        )
        if layer_id not in project.timeline.layers:
            project.timeline.layers.append(layer_id)
        project.timeline.items.append(item)
        _mark_preview_stale(project)
        self.store.put(project)
        return {"success": True, "item": item.model_dump(), "timeline": project.timeline.model_dump()}

    def patch_timeline_item(self, project_id: str, item_id: str, patch: TimelineItemPatch) -> dict:
        project = self.store.get(project_id)
        if not project.timeline:
            raise VideoDesignError(SCENE_NOT_READY, "Timeline has not been created.")
        for item in project.timeline.items:
            if item.item_id == item_id:
                if patch.start_seconds is not None:
                    item.start_seconds = patch.start_seconds
                if patch.end_seconds is not None:
                    item.end_seconds = patch.end_seconds
                if item.type != "media" and (patch.start_seconds is not None or patch.end_seconds is not None):
                    item.start_seconds, item.end_seconds = _clamp_item_bounds(
                        item.start_seconds,
                        item.end_seconds,
                        _scene_timeline_bounds(project, item.scene_id),
                    )
                if patch.source_ref is not None:
                    item.source_ref = patch.source_ref
                if patch.transform is not None:
                    item.transform = patch.transform
                if patch.style is not None:
                    item.style = patch.style
                _mark_preview_stale(project)
                self.store.put(project)
                return {"success": True, "item": item.model_dump()}
        raise VideoDesignError(SCENE_NOT_FOUND, "Timeline item does not exist.")

    def delete_timeline_item(self, project_id: str, item_id: str) -> dict:
        project = self.store.get(project_id)
        if not project.timeline:
            raise VideoDesignError(SCENE_NOT_READY, "Timeline has not been created.")
        before = len(project.timeline.items)
        deleted_item = next((item for item in project.timeline.items if item.item_id == item_id), None)
        project.timeline.items = [item for item in project.timeline.items if item.item_id != item_id]
        if len(project.timeline.items) == before:
            raise VideoDesignError(SCENE_NOT_FOUND, "Timeline item does not exist.")
        if deleted_item and deleted_item.type == "music":
            _delete_project_file(project, str(deleted_item.source_ref.get("local_path") or ""))
        _mark_preview_stale(project)
        self.store.put(project)
        return {"success": True, "timeline": project.timeline.model_dump()}

    def set_scene_transition(self, project_id: str, scene_id: str, request: TransitionRequest) -> dict:
        project = self.store.get(project_id)
        if not project.timeline:
            raise VideoDesignError(SCENE_NOT_READY, "Timeline has not been created.")
        _set_transition_for_scene(project, scene_id, request.transition_id, request.duration_seconds)
        _mark_preview_stale(project)
        self.store.put(project)
        return {"success": True, "timeline": project.timeline.model_dump()}

    def apply_all_transitions(self, project_id: str, request: TransitionRequest) -> dict:
        project = self.store.get(project_id)
        if not project.timeline:
            raise VideoDesignError(SCENE_NOT_READY, "Timeline has not been created.")
        for scene_id in _transitionable_scene_ids(project):
            _set_transition_for_scene(project, scene_id, request.transition_id, request.duration_seconds)
        _mark_preview_stale(project)
        self.store.put(project)
        return {"success": True, "timeline": project.timeline.model_dump()}

    def randomize_transitions(self, project_id: str) -> dict:
        project = self.store.get(project_id)
        if not project.timeline:
            raise VideoDesignError(SCENE_NOT_READY, "Timeline has not been created.")
        choices = ["fade", "dissolve", "slide_left", "slide_right", "zoom_in", "whip_pan", "flash_cut"]
        for index, scene_id in enumerate(_transitionable_scene_ids(project)):
            transition_id = choices[index % len(choices)]
            _set_transition_for_scene(project, scene_id, transition_id, 0.35)
        _mark_preview_stale(project)
        self.store.put(project)
        return {"success": True, "timeline": project.timeline.model_dump()}

    def sfx_catalog(self) -> dict:
        assets = _sfx_catalog_assets()
        return {
            "success": True,
            "items": [asset.model_dump() for asset in assets],
            "transition_presets": _sfx_transition_presets_for_ui(),
        }

    def sfx_file_path(self, asset_id: str) -> Path:
        asset = _sfx_asset(asset_id)
        path = Path(asset.local_path)
        if not path.exists():
            raise VideoDesignError(PREVIEW_RENDER_FAILED, "SFX file does not exist.", retryable=True)
        return path

    def suggest_sfx(self, project_id: str, request: SFXSuggestRequest) -> dict:
        project = self.store.get(project_id)
        if not project.timeline:
            raise VideoDesignError(SCENE_NOT_READY, "Timeline has not been created.")
        suggestions = _suggest_sfx_for_project(project, request)
        project.sfx_suggestions = suggestions
        self.store.put(project)
        return {"success": True, "suggestions": [item.model_dump() for item in suggestions]}

    def sfx_suggestions(self, project_id: str) -> dict:
        project = self.store.get(project_id)
        return {"success": True, "suggestions": [item.model_dump() for item in project.sfx_suggestions]}

    def apply_sfx_suggestions(self, project_id: str, request: SFXApplyRequest) -> dict:
        project = self.store.get(project_id)
        if not project.timeline:
            raise VideoDesignError(SCENE_NOT_READY, "Timeline has not been created.")
        selected_ids = set(request.suggestion_ids or [])
        suggestions = [
            item
            for item in project.sfx_suggestions
            if item.status == "proposed" and (not selected_ids or item.suggestion_id in selected_ids)
        ]
        if not suggestions:
            return {"success": True, "applied": [], "timeline": project.timeline.model_dump()}

        existing_event_ids = {
            item.source_ref.get("event_id")
            for item in project.timeline.items
            if item.type == "sfx" and item.source_ref.get("event_id")
        }
        applied = []
        for suggestion in suggestions:
            if suggestion.suggestion_id in request.volume_overrides:
                suggestion.volume = _clamp_sfx_volume(request.volume_overrides[suggestion.suggestion_id])
            if suggestion.event_id in existing_event_ids:
                suggestion.status = "applied"
                continue
            asset = _sfx_asset(suggestion.asset_id)
            start = max(0.0, float(suggestion.time_seconds))
            sfx_duration = max(
                0.05,
                min(float(asset.duration_seconds or 0.25), float(suggestion.duration_hint_seconds or asset.duration_seconds or 0.25)),
            )
            end = min(
                max(start + 0.05, start + sfx_duration),
                max(start + 0.05, float(project.timeline.duration_seconds or start + 0.25)),
            )
            item = TimelineItem(
                item_id=f"itm_{uuid.uuid4().hex}",
                layer_id="sfx",
                scene_id=suggestion.scene_id,
                type="sfx",
                start_seconds=round(start, 3),
                end_seconds=round(end, 3),
                source_ref={
                    "asset_id": asset.asset_id,
                    "audio_url": asset.audio_url,
                    "event_id": suggestion.event_id,
                    "event_type": suggestion.event_type,
                    "label": suggestion.label,
                },
                style={"volume": suggestion.volume, "enabled": True},
            )
            project.timeline.items.append(item)
            if "sfx" not in project.timeline.layers:
                project.timeline.layers.append("sfx")
            suggestion.status = "applied"
            existing_event_ids.add(suggestion.event_id)
            applied.append(item)

        _mark_preview_stale(project)
        self.store.put(project)
        return {
            "success": True,
            "applied": [item.model_dump() for item in applied],
            "suggestions": [item.model_dump() for item in project.sfx_suggestions],
            "timeline": project.timeline.model_dump(),
        }

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






def _renderable_scenes(project: VideoDesignProject) -> list[ScenePlan]:
    return [scene for scene in project.scenes if scene.approval_state != "placeholder_allowed"]


def _assign_global_tts_offsets(scenes: list[ScenePlan], total_duration: float) -> list[SceneAudioOffset]:
    if not scenes:
        return []
    safe_total = round(max(0.05, total_duration), 3)
    weights = [max(0.05, estimate_duration(scene.tts_text or scene.voiceover_text)) for scene in scenes]
    total_weight = sum(weights) or len(scenes)
    offsets: list[SceneAudioOffset] = []
    current = 0.0
    for index, scene in enumerate(scenes):
        if index == len(scenes) - 1:
            end = safe_total
        else:
            duration = safe_total * (weights[index] / total_weight)
            end = min(safe_total, round(current + max(0.05, duration), 3))
        offsets.append(
            SceneAudioOffset(
                scene_id=scene.scene_id,
                start_seconds=round(current, 3),
                end_seconds=round(max(end, current + 0.05), 3),
            )
        )
        current = offsets[-1].end_seconds
    offsets[-1].end_seconds = safe_total
    return offsets


def _delete_project_file(project: VideoDesignProject, file_path: str) -> bool:
    if not file_path:
        return False
    try:
        path = Path(file_path).resolve()
        project_root = (settings.storage_dir / project.project_id).resolve()
        path.relative_to(project_root)
    except (OSError, ValueError):
        return False
    if not path.exists() or not path.is_file():
        return False
    try:
        path.unlink()
        return True
    except OSError:
        return False






































































































def _sfx_catalog_dir() -> Path:
    path = settings.storage_dir / "_sfx_catalog"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _sfx_catalog_assets() -> list[SFXAsset]:
    return list(_static_sfx_catalog_assets())


def _sfx_transition_presets_for_ui() -> list[dict]:
    items = []
    for transition_id, preset in SFX_TRANSITION_PRESETS.items():
        asset_id = _sfx_asset_for_transition(transition_id)
        asset = _sfx_asset(asset_id) if asset_id else None
        items.append(
            {
                "transition_id": transition_id,
                "enabled": bool(preset.get("enabled")),
                "category": preset.get("category", "none"),
                "asset_id": asset.asset_id if asset else "",
                "asset_name": asset.name if asset else "No SFX",
                "volume": float(preset.get("volume", 0)),
                "duration_seconds": float(preset.get("duration_seconds", 0)),
            }
        )
    return items


def _sfx_asset(asset_id: str) -> SFXAsset:
    static_asset = next((asset for asset in _static_sfx_catalog_assets() if asset.asset_id == asset_id), None)
    if static_asset:
        return static_asset
    return _generated_sfx_asset(asset_id)


@lru_cache(maxsize=1)
def _static_sfx_catalog_assets() -> tuple[SFXAsset, ...]:
    catalog_path = STATIC_SFX_ROOT / "catalog.json"
    if not catalog_path.exists():
        return tuple()
    try:
        items = json.loads(catalog_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return tuple()
    assets: list[SFXAsset] = []
    for item in items:
        filename = str(item.get("filename") or "").strip()
        asset_id = str(item.get("asset_id") or "").strip()
        if not filename or not asset_id:
            continue
        local_path = STATIC_SFX_ROOT / filename
        if not local_path.exists():
            continue
        category = str(item.get("category") or "sfx").strip()
        duration = _safe_audio_duration(local_path)
        assets.append(
            SFXAsset(
                asset_id=asset_id,
                name=str(item.get("name") or asset_id),
                category=category,
                audio_url=str(item.get("audio_url") or f"/static/sfx/mixkit/{filename}"),
                local_path=str(local_path),
                duration_seconds=duration,
                default_volume=float(STATIC_SFX_DEFAULT_VOLUME.get(category, 0.28)),
                recommended_events=list(STATIC_SFX_RECOMMENDED_EVENTS.get(category, ["transition", "caption_word"])),
            )
        )
    return tuple(assets)


def _safe_audio_duration(path: Path) -> float:
    try:
        return max(0.05, round(measure_audio_duration(path), 3))
    except Exception:
        return 0.35


def _generated_sfx_asset(asset_id: str) -> SFXAsset:
    definition = next((item for item in LEGACY_SFX_DEFS if item["asset_id"] == asset_id), None)
    if not definition:
        raise VideoDesignError(SCENE_NOT_FOUND, "SFX asset does not exist.")
    local_path = _ensure_sfx_file(definition)
    return SFXAsset(
        asset_id=definition["asset_id"],
        name=definition["name"],
        category=definition["category"],
        audio_url=f"/api/videodesign/sfx/{definition['asset_id']}/file",
        local_path=str(local_path),
        duration_seconds=float(definition["duration_seconds"]),
        default_volume=float(definition["default_volume"]),
        recommended_events=list(definition["recommended_events"]),
    )


def _ensure_sfx_file(definition: dict) -> Path:
    path = _sfx_catalog_dir() / f"{definition['asset_id']}.wav"
    if path.exists():
        return path
    _write_tone_wav(
        path,
        duration_seconds=float(definition["duration_seconds"]),
        frequency=float(definition["frequency"]),
        sweep_to=float(definition.get("sweep_to") or definition["frequency"]),
        volume=float(definition["default_volume"]),
    )
    return path


def _write_tone_wav(path: Path, duration_seconds: float, frequency: float, sweep_to: float, volume: float) -> None:
    frame_count = max(1, int(SFX_SAMPLE_RATE * duration_seconds))
    max_amp = int(32767 * max(0.05, min(volume, 0.75)))
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SFX_SAMPLE_RATE)
        frames = bytearray()
        for index in range(frame_count):
            position = index / max(1, frame_count - 1)
            freq = frequency + (sweep_to - frequency) * position
            envelope = math.sin(math.pi * position)
            if position < 0.08:
                envelope *= position / 0.08
            sample = int(math.sin(2 * math.pi * freq * (index / SFX_SAMPLE_RATE)) * max_amp * envelope)
            frames.extend(sample.to_bytes(2, "little", signed=True))
        wav.writeframes(bytes(frames))


def _suggest_sfx_for_project(project: VideoDesignProject, request: SFXSuggestRequest) -> list[SFXSuggestion]:
    media_items = sorted(
        [item for item in (project.timeline.items if project.timeline else []) if item.type == "media"],
        key=lambda item: item.start_seconds,
    )
    suggestions: list[SFXSuggestion] = []
    if request.include_hook and media_items:
        asset_id = _sfx_asset_for_category("impact")
        if asset_id:
            suggestions.append(
                _make_sfx_suggestion(
                    project,
                    event_id="evt_hook_start",
                    scene_id=media_items[0].scene_id,
                    event_type="hook",
                    time_seconds=0,
                    asset_id=asset_id,
                    label="Opening hook impact",
                    reason="Adds a subtle accent at the start of the video.",
                    priority=0.95,
                )
            )
    if request.include_transitions:
        for transition in sorted([item for item in project.timeline.items if item.type == "transition"], key=lambda item: item.start_seconds):
            transition_id = str(transition.style.get("transition_id") or transition.source_ref.get("transition_id") or "fade")
            preset = _sfx_transition_preset(transition_id)
            if not preset.get("enabled"):
                continue
            transition_label = transition_id.replace("_", " ")
            asset_id = _sfx_asset_for_transition(str(transition_id))
            if not asset_id:
                continue
            duration_hint = min(
                float(preset.get("duration_seconds", 0.35) or 0.35),
                max(0.08, float(transition.end_seconds - transition.start_seconds) + 0.1),
            )
            suggestions.append(
                _make_sfx_suggestion(
                    project,
                    event_id=f"evt_transition_{transition.item_id}",
                    scene_id=transition.scene_id,
                    event_type="transition",
                    time_seconds=transition.start_seconds,
                    asset_id=asset_id,
                    label=f"{transition_label} transition",
                    reason=f"Transition uses {transition_label}, so a short accent can make the cut feel intentional.",
                    priority=0.9,
                    volume=float(preset.get("volume", 0.25)),
                    duration_hint_seconds=duration_hint,
                )
            )
    if request.include_icons:
        for icon in sorted([item for item in project.timeline.items if item.type == "icon"], key=lambda item: item.start_seconds):
            icon_id = str(icon.source_ref.get("icon_id") or "icon")
            asset_id = _sfx_asset_for_icon(icon_id)
            if not asset_id:
                continue
            suggestions.append(
                _make_sfx_suggestion(
                    project,
                    event_id=f"evt_icon_{icon.item_id}",
                    scene_id=icon.scene_id,
                    event_type="icon",
                    time_seconds=icon.start_seconds,
                    asset_id=asset_id,
                    label=f"{icon_id.replace('_', ' ')} icon",
                    reason="Icon appears on screen and can use a small emphasis sound.",
                    priority=0.72,
                )
            )
    if request.include_text:
        for text_item in sorted([item for item in project.timeline.items if item.type == "text"], key=lambda item: item.start_seconds):
            text = str(text_item.source_ref.get("text") or "").strip()
            if not text:
                continue
            asset_id = _sfx_asset_for_category("pop")
            if not asset_id:
                continue
            suggestions.append(
                _make_sfx_suggestion(
                    project,
                    event_id=f"evt_text_{text_item.item_id}",
                    scene_id=text_item.scene_id,
                    event_type="text_overlay",
                    time_seconds=text_item.start_seconds,
                    asset_id=asset_id,
                    label="Text pop",
                    reason="Text overlay starts here.",
                    priority=0.62,
                )
            )
    if request.include_caption_words:
        for media in media_items:
            scene = next((item for item in project.scenes if item.scene_id == media.scene_id), None)
            if not scene:
                continue
            suggestions.extend(_caption_word_sfx_suggestions(project, scene, media))

    return _dedupe_sfx_suggestions(suggestions, request.max_suggestions)


def _make_sfx_suggestion(
    project: VideoDesignProject,
    event_id: str,
    scene_id: str,
    event_type: str,
    time_seconds: float,
    asset_id: str,
    label: str,
    reason: str,
    priority: float,
    volume: float | None = None,
    duration_hint_seconds: float | None = None,
) -> SFXSuggestion:
    asset = _sfx_asset(asset_id)
    return SFXSuggestion(
        suggestion_id=f"sgx_{uuid.uuid4().hex}",
        event_id=event_id,
        project_id=project.project_id,
        scene_id=scene_id,
        event_type=event_type,
        time_seconds=round(max(0.0, float(time_seconds)), 3),
        duration_hint_seconds=round(max(0.05, float(duration_hint_seconds or asset.duration_seconds)), 3),
        label=label,
        reason=reason,
        asset_id=asset.asset_id,
        volume=_clamp_sfx_volume(volume if volume is not None else asset.default_volume),
    )


def _caption_word_sfx_suggestions(project: VideoDesignProject, scene: ScenePlan, media: TimelineItem) -> list[SFXSuggestion]:
    text = scene.caption_text or scene.tts_text or scene.voiceover_text
    words = re.findall(r"[A-Za-z0-9']+", text or "")
    if not words:
        return []
    duration = max(0.25, float(media.end_seconds - media.start_seconds))
    indexes = _important_caption_word_indexes(words)
    suggestions = []
    for index in indexes[:2]:
        word = words[index]
        local = duration * (index / max(1, len(words)))
        asset_id = _sfx_asset_for_category("ding" if any(char.isdigit() for char in word) else "pop")
        if not asset_id:
            continue
        suggestions.append(
            _make_sfx_suggestion(
                project,
                event_id=f"evt_caption_{scene.scene_id}_{index}",
                scene_id=scene.scene_id,
                event_type="caption_word",
                time_seconds=float(media.start_seconds) + local,
                asset_id=asset_id,
                label=f"Caption accent: {word}",
                reason="Important caption word can use a small pop, not every word.",
                priority=0.5 if index else 0.68,
            )
        )
    return suggestions


def _important_caption_word_indexes(words: list[str]) -> list[int]:
    indexes = [0]
    for index, word in enumerate(words):
        clean = word.strip("'").lower()
        if index == 0:
            continue
        if len(clean) <= 2:
            continue
        if any(char.isdigit() for char in clean) or word.isupper() or clean in {"now", "stop", "secret", "never", "always", "money", "truth", "watch"}:
            indexes.append(index)
        if len(indexes) >= 3:
            break
    return sorted(set(indexes))


def _dedupe_sfx_suggestions(suggestions: list[SFXSuggestion], limit: int) -> list[SFXSuggestion]:
    priority = {
        "hook": 5,
        "transition": 4,
        "icon": 3,
        "text_overlay": 2,
        "caption_word": 1,
    }
    sorted_items = sorted(
        suggestions,
        key=lambda item: (-priority.get(item.event_type, 0), item.time_seconds),
    )
    accepted: list[SFXSuggestion] = []
    for suggestion in sorted_items:
        if any(abs(suggestion.time_seconds - existing.time_seconds) < 0.45 for existing in accepted):
            continue
        accepted.append(suggestion)
        if len(accepted) >= limit:
            break
    return sorted(accepted, key=lambda item: item.time_seconds)


def _sfx_asset_for_transition(transition_id: str) -> str:
    preset = _sfx_transition_preset(transition_id)
    if not preset.get("enabled"):
        return ""
    return _sfx_asset_from_preset(preset)


def _sfx_transition_preset(transition_id: str) -> dict:
    return SFX_TRANSITION_PRESETS.get(str(transition_id or "fade"), SFX_TRANSITION_PRESETS["fade"])


def _sfx_asset_from_preset(preset: dict) -> str:
    for asset_id in preset.get("asset_ids", []):
        if _static_sfx_asset_exists(str(asset_id)):
            return str(asset_id)
    category = str(preset.get("category") or "")
    if category and category != "none":
        return _sfx_asset_for_category(category)
    return ""


def _static_sfx_asset_exists(asset_id: str) -> bool:
    return any(item.asset_id == asset_id for item in _static_sfx_catalog_assets())


def _sfx_asset_for_icon(icon_id: str) -> str:
    if icon_id in {"check", "starburst"}:
        return _sfx_asset_for_category("ding")
    if icon_id in {"arrow_right", "pointer"}:
        return _sfx_asset_for_category("whoosh")
    return _sfx_asset_for_category("click")


def _sfx_asset_for_category(category: str) -> str:
    asset = next((item for item in _static_sfx_catalog_assets() if item.category == category), None)
    return asset.asset_id if asset else ""


def _clamp_sfx_volume(value: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = 0.35
    return round(max(0.0, min(1.0, number)), 3)


def _mark_preview_stale(project: VideoDesignProject) -> None:
    preview = project.smooth_preview
    if preview.preview_path and Path(preview.preview_path).exists():
        preview.status = "stale"
    else:
        preview.status = "missing"
        preview.preview_url = ""
        preview.preview_path = ""
    if project.timeline:
        preview.timeline_id = project.timeline.timeline_id


def _reset_smooth_preview(project: VideoDesignProject) -> None:
    _delete_project_file(project, project.smooth_preview.preview_path)
    project.smooth_preview = SmoothPreview()


def _project_sort_value(project: VideoDesignProject) -> str:
    return project.smooth_preview.updated_at or project.created_at or project.project_id


def _project_title(project: VideoDesignProject) -> str:
    text = (project.idea or project.script or project.project_id).strip()
    first_line = next((line.strip() for line in text.splitlines() if line.strip()), project.project_id)
    return first_line[:90]


def _project_stage(project: VideoDesignProject) -> str:
    if project.smooth_preview.status == "ready" and project.smooth_preview.preview_path:
        return "export_ready"
    if project.timeline:
        return "studio"
    if any(scene.material_asset_id for scene in project.scenes):
        return "materials_downloaded"
    if project.candidates:
        return "review_materials"
    if project.scenes:
        return "plan"
    if project.script.strip():
        return "script"
    return "idea"


def _project_summary(project: VideoDesignProject) -> dict:
    approved_count = sum(1 for scene in project.scenes if scene.selected_candidate_id)
    downloaded_count = sum(1 for scene in project.scenes if scene.material_asset_id)
    export_ready = bool(
        project.smooth_preview.status == "ready"
        and project.smooth_preview.preview_path
        and Path(project.smooth_preview.preview_path).exists()
    )
    return {
        "project_id": project.project_id,
        "title": _project_title(project),
        "stage": _project_stage(project),
        "created_at": project.created_at,
        "target_duration_seconds": project.target_duration_seconds,
        "aspect_ratio": project.aspect_ratio,
        "scene_count": len(project.scenes),
        "candidate_count": len(project.candidates),
        "approved_count": approved_count,
        "downloaded_count": downloaded_count,
        "has_timeline": bool(project.timeline),
        "timeline_duration_seconds": project.timeline.duration_seconds if project.timeline else 0,
        "preview_status": project.smooth_preview.status,
        "export_ready": export_ready,
    }


def _smooth_preview_url(project_id: str, updated_at: str) -> str:
    cache_key = re.sub(r"[^0-9A-Za-z]", "", updated_at) or uuid.uuid4().hex
    return f"/api/videodesign/projects/{project_id}/preview/file?v={cache_key}"


def _export_url(project_id: str) -> str:
    return f"/api/videodesign/projects/{project_id}/export/file"


def _safe_filename(value: str) -> str:
    filename = re.sub(r"[^0-9A-Za-z._-]+", "-", value.strip()).strip(".-")
    return filename[:80] or "videodesign-export"


async def _render_smooth_preview_file(project: VideoDesignProject) -> Path:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise VideoDesignError(PREVIEW_RENDER_FAILED, "FFmpeg is not available for smooth preview rendering.", retryable=True)
    if not project.timeline:
        raise VideoDesignError(SCENE_NOT_READY, "Timeline has not been created.")

    media_items = sorted(
        [item for item in project.timeline.items if item.type == "media"],
        key=lambda item: item.start_seconds,
    )
    if not media_items:
        raise VideoDesignError(SCENE_NOT_READY, "Timeline has no media items to render.")

    for item in media_items:
        asset = _asset(project, str(item.source_ref.get("asset_id") or ""))
        await _ensure_preview_proxy(asset, project.aspect_ratio)

    output_dir = settings.storage_dir / project.project_id / "previews"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "timeline_preview.mp4"
    temp_path = output_dir / f"timeline_preview.{uuid.uuid4().hex}.tmp.mp4"

    transition_by_scene: dict[str, TimelineItem] = {}
    for item in project.timeline.items:
        if item.type != "transition":
            continue
        transition_id = item.style.get("transition_id") or item.source_ref.get("transition_id")
        if transition_id and transition_id != "none":
            transition_by_scene[item.scene_id] = item
    command = [ffmpeg, "-y"]
    width, height = _proxy_resolution(project.aspect_ratio)
    incoming_transition = 0.0
    input_durations: list[float] = []
    input_trim_starts: list[float] = []
    for index, item in enumerate(media_items):
        asset = _asset(project, str(item.source_ref.get("asset_id") or ""))
        input_path = Path(asset.proxy_path or asset.local_path)
        has_video_stream = await _has_video_stream(input_path)
        if not input_path.exists():
            raise VideoDesignError(PREVIEW_RENDER_FAILED, f"Media file does not exist for scene {item.scene_id}.", retryable=True)
        scene_duration = max(TIMELINE_MIN_ITEM_DURATION, float(item.end_seconds - item.start_seconds))
        input_duration = scene_duration + (incoming_transition if index > 0 else 0)
        input_durations.append(input_duration)
        if has_video_stream:
            input_trim_starts.append(max(0.0, float(item.source_ref.get("trim_start_seconds") or 0)))
            command.extend(["-stream_loop", "-1", "-i", str(input_path)])
        else:
            input_trim_starts.append(0.0)
            command.extend(
                [
                    "-f",
                    "lavfi",
                    "-t",
                    _ffmpeg_seconds(input_duration),
                    "-i",
                    f"color=c=black:s={width}x{height}:r=30",
                ]
            )
        transition = transition_by_scene.get(item.scene_id)
        incoming_transition = _transition_duration_for_render(transition, scene_duration) if transition else 0.0

    audio_input_index: int | None = None
    if project.voiceover_track.audio_path and Path(project.voiceover_track.audio_path).exists():
        audio_input_index = len(media_items)
        command.extend(["-i", str(Path(project.voiceover_track.audio_path))])
    music_inputs: list[tuple[TimelineItem, int, Path]] = []
    for item in sorted([entry for entry in project.timeline.items if entry.type == "music"], key=lambda entry: entry.start_seconds):
        if item.style.get("enabled") is False:
            continue
        path = Path(str(item.source_ref.get("local_path") or ""))
        if not path.exists():
            continue
        input_index = len(media_items) + (1 if audio_input_index is not None else 0) + len(music_inputs)
        if item.style.get("loop", True):
            command.extend(["-stream_loop", "-1"])
        command.extend(["-i", str(path)])
        music_inputs.append((item, input_index, path))
    sfx_inputs: list[tuple[TimelineItem, int, SFXAsset]] = []
    for item in sorted([entry for entry in project.timeline.items if entry.type == "sfx"], key=lambda entry: entry.start_seconds):
        if item.style.get("enabled") is False:
            continue
        asset_id = str(item.source_ref.get("asset_id") or "")
        if not asset_id:
            continue
        try:
            asset = _sfx_asset(asset_id)
        except VideoDesignError:
            continue
        path = Path(asset.local_path)
        if not path.exists():
            continue
        input_index = len(media_items) + (1 if audio_input_index is not None else 0) + len(music_inputs) + len(sfx_inputs)
        command.extend(["-i", str(path)])
        sfx_inputs.append((item, input_index, asset))

    filter_parts: list[str] = []
    for index, item in enumerate(media_items):
        filter_parts.append(_media_render_filter(index, item, input_durations[index], width, height, input_trim_starts[index]))

    chain = "v0"
    for index, item in enumerate(media_items[:-1]):
        transition = transition_by_scene.get(item.scene_id)
        next_label = f"v{index + 1}"
        output_label = f"x{index}"
        if transition:
            scene_duration = max(TIMELINE_MIN_ITEM_DURATION, float(item.end_seconds - item.start_seconds))
            duration = _transition_duration_for_render(transition, scene_duration)
            offset = max(0.0, float(item.end_seconds) - duration)
            transition_id = _ffmpeg_transition_id(transition)
            filter_parts.append(
                f"[{chain}][{next_label}]xfade=transition={transition_id}:duration={_ffmpeg_seconds(duration)}:"
                f"offset={_ffmpeg_seconds(offset)},format=yuv420p[{output_label}]"
            )
        else:
            filter_parts.append(f"[{chain}][{next_label}]concat=n=2:v=1:a=0,setpts=PTS-STARTPTS,format=yuv420p[{output_label}]")
        chain = output_label

    duration = max(TIMELINE_MIN_ITEM_DURATION, float(project.timeline.duration_seconds or media_items[-1].end_seconds))
    audio_label = _append_audio_mix_filters(filter_parts, audio_input_index, music_inputs, sfx_inputs, duration)
    command.extend(["-filter_complex", ";".join(filter_parts), "-map", f"[{chain}]"])
    if audio_label:
        command.extend(["-map", f"[{audio_label}]", "-c:a", "aac", "-b:a", "160k"])
    else:
        command.append("-an")
    command.extend(
        [
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "23",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            "-t",
            _ffmpeg_seconds(duration),
            str(temp_path),
        ]
    )

    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    timeout = max(180.0, duration * 10)
    try:
        _, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except asyncio.TimeoutError as exc:
        process.kill()
        await process.communicate()
        if temp_path.exists():
            temp_path.unlink()
        raise VideoDesignError(PREVIEW_RENDER_FAILED, "Smooth preview render timed out.", retryable=True) from exc

    if process.returncode != 0 or not temp_path.exists():
        if temp_path.exists():
            temp_path.unlink()
        message = (stderr or b"").decode(errors="ignore").strip()[-1400:]
        raise VideoDesignError(PREVIEW_RENDER_FAILED, f"FFmpeg smooth preview render failed: {message}", retryable=True)

    if output_path.exists():
        output_path.unlink()
    temp_path.replace(output_path)
    return output_path


async def _has_video_stream(path: Path) -> bool:
    if not path.exists():
        return False
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return True
    process = await asyncio.create_subprocess_exec(
        ffprobe,
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=codec_type",
        "-of",
        "csv=p=0",
        str(path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout=20)
    except asyncio.TimeoutError:
        process.kill()
        await process.communicate()
        return False
    return process.returncode == 0 and "video" in stdout.decode(errors="ignore").lower()


def _media_render_filter(index: int, item: TimelineItem, duration: float, width: int, height: int, trim_start: float | None = None) -> str:
    trim_start = max(0.0, float(item.source_ref.get("trim_start_seconds") if trim_start is None else trim_start) or 0)
    filters = [
        f"trim=start={_ffmpeg_seconds(trim_start)}:duration={_ffmpeg_seconds(duration)}",
        "setpts=PTS-STARTPTS",
    ]
    if item.transform.get("flip_horizontal"):
        filters.append("hflip")
    filters.extend(
        [
            f"scale={width}:{height}:force_original_aspect_ratio=increase",
            f"crop={width}:{height}",
            "fps=30",
        ]
    )
    effects = item.source_ref.get("effects") or {}
    eq = _eq_filter(effects)
    if eq:
        filters.append(eq)
    filters.append("format=yuv420p")
    return f"[{index}:v]{','.join(filters)}[v{index}]"


def _music_trim_bounds(item: TimelineItem) -> tuple[float, float]:
    source_duration = max(0.05, float(item.source_ref.get("duration_seconds") or 0.05))
    trim_start = max(0.0, min(float(item.source_ref.get("trim_start_seconds") or 0), source_duration - 0.05))
    raw_end = item.source_ref.get("trim_end_seconds")
    trim_end = source_duration if raw_end in (None, "") else float(raw_end or source_duration)
    trim_end = max(trim_start + 0.05, min(trim_end, source_duration))
    return round(trim_start, 3), round(trim_end, 3)


def _append_audio_mix_filters(
    filter_parts: list[str],
    voiceover_input_index: int | None,
    music_inputs: list[tuple[TimelineItem, int, Path]],
    sfx_inputs: list[tuple[TimelineItem, int, SFXAsset]],
    duration: float,
) -> str:
    audio_labels: list[str] = []
    if voiceover_input_index is not None:
        filter_parts.append(
            f"[{voiceover_input_index}:a]atrim=0:{_ffmpeg_seconds(duration)},"
            f"asetpts=PTS-STARTPTS,volume=1.0[a_voice]"
        )
        audio_labels.append("a_voice")
    for index, (item, input_index, _path) in enumerate(music_inputs):
        start = max(0.0, float(item.start_seconds or 0))
        end = max(start + 0.05, min(float(item.end_seconds or duration), duration))
        item_duration = max(0.05, end - start)
        start_ms = max(0, int(start * 1000))
        trim_start, trim_end = _music_trim_bounds(item)
        trim_duration = max(0.05, trim_end - trim_start)
        base_volume = float(item.style.get("volume", 0.16) or 0.16)
        ducking_volume = float(item.style.get("ducking_volume", 0.08) or 0.08)
        volume = ducking_volume if voiceover_input_index is not None and item.style.get("ducking", True) else base_volume
        volume = max(0.0, min(1.0, volume))
        fade_in = max(0.0, min(float(item.style.get("fade_in_seconds", 0) or 0), item_duration / 2))
        fade_out = max(0.0, min(float(item.style.get("fade_out_seconds", 0) or 0), item_duration / 2))
        filters = [
            "aresample=44100",
            f"atrim=start={_ffmpeg_seconds(trim_start)}:end={_ffmpeg_seconds(trim_end)}",
            "asetpts=PTS-STARTPTS",
        ]
        if item.style.get("loop", True):
            filters.append(f"aloop=loop=-1:size={max(1, int(trim_duration * 44100))}")
        filters.extend(
            [
                f"atrim=0:{_ffmpeg_seconds(item_duration)}",
                "asetpts=PTS-STARTPTS",
                f"volume={volume:.3f}",
            ]
        )
        if fade_in > 0:
            filters.append(f"afade=t=in:st=0:d={_ffmpeg_seconds(fade_in)}")
        if fade_out > 0:
            filters.append(f"afade=t=out:st={_ffmpeg_seconds(max(0.0, item_duration - fade_out))}:d={_ffmpeg_seconds(fade_out)}")
        filters.append(f"adelay={start_ms}:all=1")
        label = f"a_music_{index}"
        filter_parts.append(f"[{input_index}:a]{','.join(filters)}[{label}]")
        audio_labels.append(label)
    for index, (item, input_index, asset) in enumerate(sfx_inputs):
        start_ms = max(0, int(float(item.start_seconds or 0) * 1000))
        item_duration = max(0.05, min(float(asset.duration_seconds or 0.25), float(item.end_seconds - item.start_seconds or asset.duration_seconds or 0.25)))
        volume = max(0.0, min(2.0, float(item.style.get("volume", asset.default_volume) or asset.default_volume)))
        label = f"a_sfx_{index}"
        filter_parts.append(
            f"[{input_index}:a]atrim=0:{_ffmpeg_seconds(item_duration)},asetpts=PTS-STARTPTS,"
            f"volume={volume:.3f},adelay={start_ms}:all=1[{label}]"
        )
        audio_labels.append(label)
    if not audio_labels:
        return ""
    if len(audio_labels) == 1:
        label = "aout"
        filter_parts.append(f"[{audio_labels[0]}]apad,atrim=0:{_ffmpeg_seconds(duration)}[{label}]")
        return label
    input_labels = "".join(f"[{label}]" for label in audio_labels)
    filter_parts.append(
        f"{input_labels}amix=inputs={len(audio_labels)}:duration=longest:dropout_transition=0,"
        f"atrim=0:{_ffmpeg_seconds(duration)}[aout]"
    )
    return "aout"


def _eq_filter(effects: dict) -> str:
    brightness = max(-1.0, min(1.0, float(effects.get("brightness", 1) or 1) - 1))
    contrast = max(0.0, min(4.0, float(effects.get("contrast", 1) or 1)))
    saturation = max(0.0, min(3.0, float(effects.get("saturation", 1) or 1)))
    if abs(brightness) < 0.001 and abs(contrast - 1) < 0.001 and abs(saturation - 1) < 0.001:
        return ""
    return f"eq=brightness={brightness:.4f}:contrast={contrast:.4f}:saturation={saturation:.4f}"


def _transition_duration_for_render(item: TimelineItem | None, scene_duration: float) -> float:
    if not item:
        return 0.0
    raw = item.style.get("duration_seconds") or item.source_ref.get("duration_seconds") or (item.end_seconds - item.start_seconds)
    return round(max(0.05, min(float(raw or 0.35), scene_duration - 0.05, 1.5)), 3)


def _ffmpeg_transition_id(item: TimelineItem) -> str:
    transition_id = item.style.get("transition_id") or item.source_ref.get("transition_id") or "fade"
    return {
        "clean_cut": "fade",
        "fade": "fade",
        "dissolve": "dissolve",
        "slide_left": "slideleft",
        "slide_right": "slideright",
        "slide_up": "slideup",
        "zoom_in": "zoomin",
        "zoom_out": "fade",
        "whip_pan": "smoothleft",
        "flash_cut": "fadewhite",
    }.get(str(transition_id), "fade")


def _ffmpeg_seconds(value: float) -> str:
    return f"{max(0.0, float(value)):.3f}"








def _scene_duration(scene: ScenePlan) -> float:
    return round(max(0.25, float(scene.duration_seconds or estimate_duration(scene.voiceover_text))), 2)


def _make_scene_clip(
    scene: ScenePlan,
    asset: MaterialAsset,
    duration: float,
    request: SceneClipPatch | None = None,
) -> SceneClip:
    existing = scene.clip if scene.clip and scene.clip.material_asset_id == asset.asset_id else None
    source = request.trim_source if request else "auto_start"
    requested_start = request.trim_start_seconds if request else 0
    raw_duration = max(0.0, float(asset.duration or 0))
    start = max(0.0, float(requested_start or 0))
    loop_mode = request.loop_mode if request and request.loop_mode is not None else (existing.loop_mode if existing else "none")
    status = "trim_manual" if source == "manual" else "trim_auto"

    if raw_duration and raw_duration < duration:
        start = 0.0
        end = raw_duration
        loop_mode = loop_mode if loop_mode and loop_mode != "none" else "loop_to_fill"
        status = "trim_short_loop"
    elif raw_duration:
        max_start = max(0.0, raw_duration - duration)
        start = min(start, max_start)
        end = start + duration
    else:
        end = start + duration

    base = existing or SceneClip(material_asset_id=asset.asset_id)
    transform = dict(base.transform)
    effects = dict(base.effects)
    transition = dict(base.transition)
    if request:
        if request.transform is not None:
            transform.update(request.transform)
        if request.effects is not None:
            effects.update(request.effects)
        if request.transition is not None:
            transition.update(request.transition)

    return SceneClip(
        material_asset_id=asset.asset_id,
        trim_source=source,
        trim_start_seconds=round(start, 2),
        trim_end_seconds=round(end, 2),
        duration_seconds=round(duration, 2),
        fit=base.fit,
        loop_mode=loop_mode or "none",
        status=status,
        transform=transform,
        effects=effects,
        transition=transition,
    )


def _apply_video_defaults_to_clip(clip: SceneClip, preset: dict | None) -> None:
    defaults = (preset or {}).get("video_defaults") or {}
    transform = dict(clip.transform or {})
    effects = dict(clip.effects or {})
    if defaults.get("flip_horizontal") and not transform.get("flip_horizontal"):
        transform["flip_horizontal"] = True
    for key, default_value in {
        "brightness": defaults.get("brightness"),
        "contrast": defaults.get("contrast"),
        "saturation": defaults.get("saturation"),
    }.items():
        if default_value in (None, ""):
            continue
        current = float(effects.get(key, 1) or 1)
        if abs(current - 1) < 0.001:
            effects[key] = float(default_value)
    clip.transform = transform
    clip.effects = effects


def _media_source_ref(project_id: str, scene: ScenePlan, asset: MaterialAsset, timeline_duration: float) -> dict:
    clip = scene.clip or _make_scene_clip(scene, asset, timeline_duration)
    raw_media_url = f"/api/videodesign/projects/{project_id}/materials/{asset.asset_id}/file"
    proxy_media_url = f"/api/videodesign/projects/{project_id}/materials/{asset.asset_id}/proxy" if asset.proxy_path else raw_media_url
    return {
        "source": "material_asset",
        "asset_id": asset.asset_id,
        "media_url": proxy_media_url,
        "raw_media_url": raw_media_url,
        "proxy_media_url": proxy_media_url if asset.proxy_path else "",
        "asset_duration_seconds": max(0.0, float(asset.duration or 0)),
        "timeline_duration_seconds": round(timeline_duration, 2),
        "trim_source": clip.trim_source,
        "trim_status": clip.status,
        "trim_start_seconds": clip.trim_start_seconds,
        "trim_end_seconds": clip.trim_end_seconds,
        "loop_mode": clip.loop_mode,
        "cut_strategy": clip.trim_source,
        "effects": clip.effects,
        "transition": clip.transition,
    }


def _media_transform_from_clip(scene: ScenePlan) -> dict:
    clip = scene.clip
    transform = clip.transform if clip else {}
    return {
        "fit": clip.fit if clip else "cover",
        "x": transform.get("crop_x", 50),
        "y": transform.get("crop_y", 50),
        "scale": transform.get("zoom", 1),
        "rotation": transform.get("rotation", 0),
        "flip_horizontal": bool(transform.get("flip_horizontal", False)),
    }


def _sync_scene_clip_to_timeline(project: VideoDesignProject, scene: ScenePlan, asset: MaterialAsset) -> None:
    if not project.timeline:
        return
    for item in project.timeline.items:
        if item.type != "media" or item.scene_id != scene.scene_id:
            continue
        timeline_duration = max(0.25, item.end_seconds - item.start_seconds)
        item.source_ref = _media_source_ref(project.project_id, scene, asset, timeline_duration)
        item.transform = _media_transform_from_clip(scene)
        break


def _scene_timeline_bounds(project: VideoDesignProject, scene_id: str) -> tuple[float, float]:
    if not project.timeline:
        raise VideoDesignError(SCENE_NOT_READY, "Timeline has not been created.")
    media = next((item for item in project.timeline.items if item.scene_id == scene_id and item.type == "media"), None)
    if not media:
        raise VideoDesignError(SCENE_NOT_READY, "Scene has no media timeline item.")
    return media.start_seconds, media.end_seconds


def _clamp_item_bounds(start: float, end: float, bounds: tuple[float, float]) -> tuple[float, float]:
    scene_start, scene_end = bounds
    safe_start = max(scene_start, min(float(start), scene_end - TIMELINE_MIN_ITEM_DURATION))
    safe_end = max(safe_start + TIMELINE_MIN_ITEM_DURATION, min(float(end), scene_end))
    return round(safe_start, 2), round(safe_end, 2)


def _default_layer_for_item_type(item_type: str) -> str:
    return {
        "caption": "caption_default",
        "icon": "icon",
        "music": "background_audio",
        "overlay": "overlay_default",
        "sfx": "sfx",
        "text": "text_overlay",
        "transition": "transition_out",
    }.get(item_type, "text_overlay")


def _default_transform_for_item_type(item_type: str) -> dict:
    if item_type == "icon":
        return {"x": 58, "y": 42, "scale": 1, "rotation": 0}
    if item_type == "caption":
        return {"x": 50, "y": 78, "scale": 1, "rotation": 0}
    if item_type == "text":
        return {"x": 50, "y": 18, "scale": 1, "rotation": 0}
    return {}


def _default_end_for_item_type(item_type: str, start: float, bounds: tuple[float, float]) -> float:
    if item_type in {"caption", "overlay"}:
        return bounds[1]
    if item_type == "sfx":
        return min(bounds[1], start + 0.35)
    return min(bounds[1], start + 1.8)


def _transitionable_scene_ids(project: VideoDesignProject) -> list[str]:
    if not project.timeline:
        return []
    media_items = sorted(
        [item for item in project.timeline.items if item.type == "media"],
        key=lambda item: item.start_seconds,
    )
    return [item.scene_id for item in media_items[:-1]]


def _set_transition_for_scene(project: VideoDesignProject, scene_id: str, transition_id: str, duration_seconds: float) -> None:
    if scene_id not in _transitionable_scene_ids(project):
        raise VideoDesignError(INVALID_PROJECT_INPUT, "Selected scene has no next scene for transition.")
    media = next(item for item in project.timeline.items if item.scene_id == scene_id and item.type == "media")
    project.timeline.items = [
        item for item in project.timeline.items if not (item.scene_id == scene_id and item.type == "transition")
    ]
    if transition_id == "none":
        return
    duration = max(0.05, min(float(duration_seconds or 0.35), min(1.5, media.end_seconds - media.start_seconds)))
    item = TimelineItem(
        item_id=f"itm_{uuid.uuid4().hex}",
        layer_id="transition_out",
        scene_id=scene_id,
        type="transition",
        start_seconds=round(max(media.start_seconds, media.end_seconds - duration), 2),
        end_seconds=round(media.end_seconds, 2),
        source_ref={
            "from_scene_id": scene_id,
            "transition_id": transition_id,
            "transition_pack_id": transition_id,
        },
        style={"transition_id": transition_id, "duration_seconds": round(duration, 2)},
    )
    if "transition_out" not in project.timeline.layers:
        project.timeline.layers.append("transition_out")
    project.timeline.items.append(item)


def _timeline_items_for_scene(project_id: str, scene: ScenePlan, asset: MaterialAsset, start: float, end: float, preset: dict | None = None) -> list[TimelineItem]:
    duration = end - start
    extras = (preset or {}).get("extras", {})
    overlay_pack_id = extras.get("overlay_pack_id") or "caption_shadow"
    items = [
        TimelineItem(
            item_id=f"itm_{uuid.uuid4().hex}",
            layer_id="media_base",
            scene_id=scene.scene_id,
            type="media",
            start_seconds=start,
            end_seconds=end,
            source_ref=_media_source_ref(project_id, scene, asset, duration),
            transform=_media_transform_from_clip(scene),
        ),
        TimelineItem(
            item_id=f"itm_{uuid.uuid4().hex}",
            layer_id="caption_default",
            scene_id=scene.scene_id,
            type="caption",
            start_seconds=start,
            end_seconds=end,
            source_ref={"caption_chunks": [chunk.model_dump() for chunk in scene.caption_chunks]},
            transform=_default_transform_for_item_type("caption"),
            style={"caption_style_id": "word_reveal_bold"},
        ),
        TimelineItem(
            item_id=f"itm_{uuid.uuid4().hex}",
            layer_id="text_overlay",
            scene_id=scene.scene_id,
            type="text",
            start_seconds=start,
            end_seconds=round(start + min(duration, 2.5), 2),
            source_ref={"text": "", "auto_generated": False},
            transform={"x": 50, "y": 18, "scale": 1, "rotation": 0},
        ),
    ]
    if overlay_pack_id != "none":
        items.append(
            TimelineItem(
                item_id=f"itm_{uuid.uuid4().hex}",
                layer_id="overlay_default",
                scene_id=scene.scene_id,
                type="overlay",
                start_seconds=start,
                end_seconds=end,
                source_ref={"overlay_pack_id": overlay_pack_id},
                style={"overlay_pack_id": overlay_pack_id},
            )
        )
    if scene.tts.audio_url:
        items.append(
            TimelineItem(
                item_id=f"itm_{uuid.uuid4().hex}",
                layer_id="voiceover_audio",
                scene_id=scene.scene_id,
                type="audio",
                start_seconds=start,
                end_seconds=end,
                source_ref={"audio_url": scene.tts.audio_url},
            )
        )
    return items


def _transition_item_for_scene(scene: ScenePlan, scene_end: float, preset: dict | None = None) -> TimelineItem:
    extras = (preset or {}).get("extras", {})
    transition_pack_id = _transition_id_from_preset(extras.get("transition_pack_id") or "fade", scene.order)
    start = round(max(0, scene_end - 0.35), 2)
    return TimelineItem(
        item_id=f"itm_{uuid.uuid4().hex}",
        layer_id="transition_out",
        scene_id=scene.scene_id,
        type="transition",
        start_seconds=start,
        end_seconds=round(scene_end, 2),
        source_ref={"transition_id": transition_pack_id, "transition_pack_id": transition_pack_id},
        style={"transition_id": transition_pack_id, "transition_pack_id": transition_pack_id, "duration_seconds": 0.35},
    )


def _transition_id_from_preset(transition_pack_id: str, scene_order: int) -> str:
    if transition_pack_id == "mix":
        choices = ["fade", "slide_left", "zoom_in", "dissolve"]
        return choices[(max(1, int(scene_order)) - 1) % len(choices)]
    return transition_pack_id


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
