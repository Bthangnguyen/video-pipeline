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
