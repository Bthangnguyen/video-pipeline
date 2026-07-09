import asyncio
import re
import shutil
import uuid
from datetime import datetime, timezone
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
from app.videodesign.planner import estimate_duration, make_caption_chunks, refresh_scene_orders, split_script
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
    SceneClip,
    SceneClipPatch,
    SceneAudioOffset,
    ScenePlan,
    SceneSelectionRequest,
    ScriptGenerateRequest,
    SplitSettings,
    SmoothPreview,
    TTSGenerateRequest,
    TTSMeta,
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


KEYWORD_STOPWORDS = {
    "about",
    "after",
    "again",
    "also",
    "and",
    "any",
    "are",
    "because",
    "but",
    "can",
    "could",
    "did",
    "does",
    "for",
    "from",
    "had",
    "has",
    "have",
    "her",
    "his",
    "how",
    "into",
    "its",
    "just",
    "not",
    "now",
    "off",
    "our",
    "out",
    "over",
    "she",
    "that",
    "the",
    "their",
    "them",
    "then",
    "there",
    "this",
    "too",
    "was",
    "what",
    "when",
    "will",
    "with",
    "you",
    "your",
}

TIMELINE_MIN_ITEM_DURATION = 0.25


class VideoDesignService:
    def __init__(self):
        self.store = VideoDesignStore()
        self.script_client = DeepSeekScriptClient()
        self.tts_client = TTSClient()
        self.ytdlp = YtDlpDownloader()

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
        self.store.put(project)
        return {"success": True, "project": project.model_dump(), "script_result": data}

    def plan(self, project_id: str) -> dict:
        project = self.store.get(project_id)
        if not project.script.strip():
            raise VideoDesignError(SCRIPT_REQUIRED, "Script is required before planning scenes.")
        project.scenes = split_script(project.script, project.split_settings)
        self.store.put(project)
        return {"success": True, "project_id": project.project_id, "scenes": [scene.model_dump() for scene in project.scenes]}

    def update_scene(self, project_id: str, scene_id: str, patch: dict) -> dict:
        project = self.store.get(project_id)
        scene = _scene(project, scene_id)
        for key in ("voiceover_text", "tts_text", "on_screen_text", "caption_text", "visual_brief", "matching_keywords"):
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
        self.store.put(project)
        return {"success": True, "scenes": [item.model_dump() for item in project.scenes]}

    async def generate_tts(self, project_id: str, request: TTSGenerateRequest) -> dict:
        project = self.store.get(project_id)
        provider = request.provider or project.tts_settings.provider
        voice_id = request.voice_id or project.tts_settings.voice_id
        if not request.scene_ids:
            return await self._generate_global_tts(project, provider, voice_id)
        scenes = _selected_scenes(project, request.scene_ids)
        for scene in scenes:
            text = scene.tts_text or scene.voiceover_text
            _delete_project_file(project, scene.tts.audio_path)
            result = await self.tts_client.generate(text, project.project_id, scene.scene_id, provider, voice_id)
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
        _delete_project_file(project, project.voiceover_track.audio_path)
        project.voiceover_track = VoiceoverTrack()
        self.store.put(project)
        return {"success": True, "project": project.model_dump(), "scenes": [scene.model_dump() for scene in scenes]}

    async def _generate_global_tts(self, project: VideoDesignProject, provider: str, voice_id: str) -> dict:
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

        result = await self.tts_client.generate(full_text, project.project_id, "global_voiceover", provider, voice_id)
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
        project = self.store.get(project_id)
        scenes = _selected_scenes(project, request.scene_ids)
        errors = []
        total = len(scenes)
        self._set_progress(project, "keyword_generation", "Preparing search keywords.", 0, total)
        for index, scene in enumerate(scenes, start=1):
            keywords, error = await self._smart_keywords_or_fallback(project, scene, 3)
            scene.matching_keywords = keywords
            if error:
                errors.append({"scene_id": scene.scene_id, "error": error})
            self._set_progress(
                project,
                "keyword_generation",
                f"Prepared scene {index}/{total} keywords: {', '.join(keywords[:2])}",
                index,
                total,
                {"scene_id": scene.scene_id, "fallback": bool(error)},
            )
        self.store.put(project)
        self._set_progress(project, "idle", "Keyword generation finished.", total, total)
        return {
            "success": True,
            "project_id": project.project_id,
            "scenes": [scene.model_dump() for scene in scenes],
            "errors": errors,
        }

    async def search_materials(self, project_id: str, request: MaterialsSearchRequest) -> dict:
        project = self.store.get(project_id)
        scenes = _selected_scenes(project, request.scene_ids)
        total = len(scenes)
        douyin_limit = request.douyin_min_per_scene if request.douyin_min_per_scene is not None else request.candidates_per_scene
        pinterest_limit = request.pinterest_min_per_scene
        scene_ids = {scene.scene_id for scene in scenes}
        project.search_tasks = [task for task in project.search_tasks if task.scene_id not in scene_ids]
        for scene in scenes:
            scene.search_tasks = []
        self._set_progress(project, "materials_search", "Preparing material search jobs.", 0, total)

        plans = []
        for index, scene in enumerate(scenes, start=1):
            scene.approval_state = "searching"
            keywords = await self._keywords_for_scene(project, scene, request)
            source_plan = [
                ("douyinsearch", douyin_limit),
                ("pinterestsearch", pinterest_limit),
            ]
            for source, source_limit in source_plan:
                if source_limit <= 0:
                    continue
                if len(_candidates_for_scene(project, scene.scene_id, source)) >= source_limit:
                    continue
                plans.append(
                    {
                        "index": index,
                        "scene": scene,
                        "source": source,
                        "source_limit": source_limit,
                        "keywords": keywords[: request.queries_per_scene],
                    }
                )

        self.store.put(project)
        if not plans:
            for scene in scenes:
                scene.approval_state = "needs_review" if _candidates_for_scene(project, scene.scene_id) else "planned"
            self.store.put(project)
            self._set_progress(project, "idle", "Material search finished.", total, total)
            return self.review(project_id)

        completed = 0
        progress_total = len(plans)
        lock = asyncio.Lock()
        semaphores = {
            "douyinsearch": asyncio.Semaphore(1),
            "pinterestsearch": asyncio.Semaphore(4),
        }

        async def run_plan(plan: dict) -> None:
            nonlocal completed
            scene = plan["scene"]
            source = plan["source"]
            async with semaphores[source]:
                for keyword in plan["keywords"]:
                    existing_count = len(_candidates_for_scene(project, scene.scene_id, source))
                    if existing_count >= plan["source_limit"]:
                        break
                    needed = plan["source_limit"] - existing_count
                    task = DouyinSearchTask(
                        search_task_id=f"dst_{uuid.uuid4().hex}",
                        project_id=project.project_id,
                        scene_id=scene.scene_id,
                        source=source,
                        keyword=keyword,
                        translate_to_chinese=request.translate_to_chinese if source == "douyinsearch" else False,
                        limit=max(needed, 3),
                        status="searching",
                    )
                    async with lock:
                        project.search_tasks.append(task)
                        scene.search_tasks.append(task.search_task_id)
                        self._set_progress(
                            project,
                            "materials_search",
                            f"Searching {source_label(source)} scene {plan['index']}/{total}: {keyword}",
                            completed,
                            progress_total,
                            {"scene_id": scene.scene_id, "keyword": keyword, "source": source},
                        )
                        self.store.put(project)
                    try:
                        if source == "douyinsearch":
                            response = await asyncio.wait_for(
                                douyin_service.search(
                                    SearchRequest(
                                        keyword=keyword,
                                        translate_to_chinese=request.translate_to_chinese,
                                        limit=max(needed, 3),
                                        strategy="auto",
                                    )
                                ),
                                timeout=45,
                            )
                        else:
                            response = await asyncio.wait_for(
                                pinterest_service.search(
                                    PinterestSearchRequest(
                                        keyword=keyword,
                                        limit=max(needed, 3),
                                        media_type="video",
                                        aspect_ratio="9:16",
                                    )
                                ),
                                timeout=90,
                            )
                        async with lock:
                            candidate_ids = _add_candidates(project, scene, response.items, needed, source, keyword)
                            task.status = "completed"
                            task.candidate_ids.extend(candidate_ids)
                            if candidate_ids:
                                scene.approval_state = "needs_review"
                            self.store.put(project)
                    except asyncio.TimeoutError:
                        async with lock:
                            task.status = "failed"
                            task.error = {
                                "code": MATERIAL_SEARCH_TIMEOUT,
                                "message": f"{source_label(source)} search timed out for keyword '{keyword}'.",
                                "retryable": True,
                            }
                            self.store.put(project)
                    except (DouyinSearchError, PinterestSearchError) as error:
                        async with lock:
                            task.status = "failed"
                            task.error = error.to_payload()
                            self.store.put(project)
                    except Exception as exc:
                        async with lock:
                            task.status = "failed"
                            task.error = {"code": MATERIAL_SEARCH_FAILED, "message": str(exc), "retryable": True}
                            self.store.put(project)
            async with lock:
                completed += 1
                self._set_progress(
                    project,
                    "materials_search",
                    f"Finished {source_label(source)} scene {plan['index']}/{total}: {len(_candidates_for_scene(project, scene.scene_id, source))} candidates.",
                    completed,
                    progress_total,
                    {"scene_id": scene.scene_id, "source": source},
                )
                self.store.put(project)

        await asyncio.gather(*(run_plan(plan) for plan in plans))
        for scene in scenes:
            scene.approval_state = "needs_review" if _candidates_for_scene(project, scene.scene_id) else "planned"
        self.store.put(project)
        self._set_progress(project, "idle", "Material search finished.", progress_total, progress_total)
        return self.review(project_id)

    async def materials_preflight(self, request: MaterialsPreflightRequest) -> dict:
        keyword = (request.keyword or "cat").strip() or "cat"
        results = await asyncio.gather(
            self._source_preflight("douyinsearch", douyin_service.preflight_check(keyword)),
            self._source_preflight("pinterestsearch", pinterest_service.preflight_check(keyword)),
        )
        return {"success": True, "healthy": all(result.get("success") for result in results), "keyword": keyword, "sources": results}

    async def _source_preflight(self, source: str, check):
        try:
            return await asyncio.wait_for(check, timeout=75)
        except Exception as exc:
            return {
                "success": False,
                "source": source,
                "state": "network_error",
                "checks": [
                    {
                        "name": "preflight",
                        "ok": False,
                        "message": str(exc),
                        "detail": {},
                    }
                ],
            }

    def review(self, project_id: str) -> dict:
        project = self.store.get(project_id)
        rows = []
        for scene in project.scenes:
            candidates = _candidates_for_scene(project, scene.scene_id)
            rows.append(
                {
                    "scene": scene.model_dump(),
                    "candidates": [candidate.model_dump() for candidate in candidates],
                    "search_errors": _search_errors_for_scene(project, scene.scene_id),
                }
            )
        return {"success": True, "project_id": project.project_id, "rows": rows}

    def progress(self, project_id: str) -> dict:
        project = self.store.get(project_id)
        return {"success": True, "project_id": project.project_id, "progress": project.progress.model_dump()}

    def select_scene(self, project_id: str, scene_id: str, request: SceneSelectionRequest) -> dict:
        project = self.store.get(project_id)
        scene = _scene(project, scene_id)
        if request.action == "placeholder":
            scene.approval_state = "placeholder_allowed"
            scene.selected_candidate_id = None
        elif request.action == "reject":
            candidate = _candidate(project, request.candidate_id)
            if candidate.scene_id != scene.scene_id:
                raise VideoDesignError(CANDIDATE_NOT_FOUND, "Candidate does not belong to this scene.")
            candidate.status = "rejected"
            if scene.selected_candidate_id == candidate.candidate_id:
                scene.selected_candidate_id = None
            scene.approval_state = "needs_review" if _candidates_for_scene(project, scene.scene_id) else "planned"
        elif request.action == "approve":
            candidate = _candidate(project, request.candidate_id)
            if candidate.scene_id != scene.scene_id:
                raise VideoDesignError(CANDIDATE_NOT_FOUND, "Candidate does not belong to this scene.")
            for item in project.candidates:
                if item.scene_id == scene.scene_id and item.candidate_id != candidate.candidate_id and item.status == "approved":
                    item.status = "proposed"
            candidate.status = "approved"
            scene.selected_candidate_id = candidate.candidate_id
            scene.approval_state = "approved"
        elif request.action == "manual_select":
            if not request.douyin_result_id:
                raise VideoDesignError(CANDIDATE_NOT_FOUND, "douyin_result_id is required for manual selection.")
            result = douyin_service.get_result(request.douyin_result_id)["item"]
            for item in project.candidates:
                if item.scene_id == scene.scene_id and item.status == "approved":
                    item.status = "proposed"
            candidate = _candidate_from_public_result(scene, result, len(project.candidates) + 1)
            candidate.status = "approved"
            project.candidates.append(candidate)
            scene.selected_candidate_id = candidate.candidate_id
            scene.approval_state = "approved"
        self.store.put(project)
        return {"success": True, "scene": scene.model_dump()}

    async def download_materials(self, project_id: str, request: MaterialsDownloadRequest) -> dict:
        project = self.store.get(project_id)
        scenes = _selected_scenes(project, request.scene_ids)
        downloaded = []
        skipped = []
        for scene in scenes:
            if scene.material_asset_id and not request.force:
                asset = _asset(project, scene.material_asset_id)
                await _ensure_preview_proxy(asset, project.aspect_ratio)
                downloaded.append(asset.model_dump())
                continue
            candidate = _approved_candidate_for_scene(project, scene)
            if not candidate:
                skipped.append({"scene_id": scene.scene_id, "code": SCENE_NOT_READY, "message": "Scene has no approved candidate."})
                continue
            scene.approval_state = "download_pending"
            asset_id = f"mat_{uuid.uuid4().hex}"
            output_path = settings.storage_dir / project.project_id / "materials" / f"{scene.scene_id}.mp4"
            try:
                await self._download_candidate(candidate, output_path)
            except Exception as exc:
                scene.approval_state = "approved"
                raise VideoDesignError(DOWNLOAD_FAILED, f"Could not download approved video: {exc}", retryable=True) from exc
            asset = MaterialAsset(
                asset_id=asset_id,
                project_id=project.project_id,
                scene_id=scene.scene_id,
                candidate_id=candidate.candidate_id,
                source=candidate.source,
                source_result_id=candidate.source_result_id,
                source_item_id=candidate.source_item_id,
                source_url=candidate.source_url,
                search_keyword=candidate.search_keyword,
                douyin_result_id=candidate.douyin_result_id,
                douyin_aweme_id=candidate.douyin_aweme_id,
                local_path=str(output_path),
                duration=candidate.duration,
            )
            await _ensure_preview_proxy(asset, project.aspect_ratio)
            project.material_assets.append(asset)
            scene.material_asset_id = asset.asset_id
            scene.clip = None
            scene.approval_state = "downloaded"
            downloaded.append(asset.model_dump())
        self.store.put(project)
        return {"success": True, "assets": downloaded, "skipped": skipped}

    def prune_material_candidates(self, project_id: str, request: MaterialsPruneRequest) -> dict:
        project = self.store.get(project_id)
        scenes = _selected_scenes(project, request.scene_ids)
        selected_by_scene = {scene.scene_id: scene.selected_candidate_id for scene in scenes if scene.selected_candidate_id}
        if not selected_by_scene:
            return {"success": True, "removed": 0, "kept": 0, "scene_ids": []}

        removed_ids = []
        kept = []
        for candidate in project.candidates:
            selected_id = selected_by_scene.get(candidate.scene_id)
            if selected_id and candidate.candidate_id != selected_id:
                removed_ids.append(candidate.candidate_id)
                continue
            kept.append(candidate)
        project.candidates = kept
        for scene in scenes:
            candidate = _approved_candidate_for_scene(project, scene)
            if candidate:
                scene.approval_state = "downloaded" if scene.material_asset_id else "approved"
            elif scene.selected_candidate_id:
                scene.selected_candidate_id = None
                scene.approval_state = "planned"
        self.store.put(project)
        return {
            "success": True,
            "removed": len(removed_ids),
            "kept": len(selected_by_scene),
            "scene_ids": list(selected_by_scene.keys()),
        }

    async def _download_candidate(self, candidate: MediaCandidate, output_path: Path) -> None:
        ytdlp_error = None
        source_url = _download_source_url(candidate)
        if source_url:
            try:
                await self.ytdlp.download(
                    source_url,
                    output_path,
                    _cookie_file_for_source(candidate.source),
                    _cookie_header_for_source(candidate.source),
                )
                return
            except Exception as exc:
                ytdlp_error = exc

        try:
            if candidate.source == "pinterestsearch":
                result = pinterest_service.store.get(candidate.source_result_id)
                if not result:
                    raise VideoDesignError(DOWNLOAD_FAILED, "Pinterest result expired.", retryable=True)
                if _is_blob_url(result.media_remote_url):
                    raise VideoDesignError(DOWNLOAD_FAILED, "Pinterest returned a browser-local blob URL.", retryable=True)
                await pinterest_service.media_proxy.download_to_file(result, output_path)
            else:
                result = douyin_service.store.get(candidate.source_result_id or candidate.douyin_result_id)
                if result:
                    await douyin_service.stream_proxy.download_to_file(result, output_path)
                else:
                    remote_url = candidate.remote_download_url or candidate.remote_stream_url
                    if not remote_url:
                        raise VideoDesignError(
                            DOWNLOAD_FAILED,
                            "Douyin result expired and this candidate has no stored media URL. Re-search this scene before downloading.",
                            retryable=True,
                        )
                    await douyin_service.stream_proxy.download_url_to_file(remote_url, output_path)
        except Exception as exc:
            if ytdlp_error:
                raise VideoDesignError(
                    DOWNLOAD_FAILED,
                    f"{ytdlp_error}; fallback download failed: {exc}",
                    retryable=True,
                ) from exc
            raise

    async def _keywords_for_scene(
        self,
        project: VideoDesignProject,
        scene: ScenePlan,
        request: MaterialsSearchRequest,
    ) -> list[str]:
        if request.use_smart_keywords:
            keywords, _error = await self._smart_keywords_or_fallback(project, scene, request.queries_per_scene)
            return keywords[: request.queries_per_scene]
        keywords = _normalize_keywords(scene.matching_keywords, request.queries_per_scene)
        if keywords:
            return keywords
        keywords = _fallback_keywords_for_scene(project, scene, request.queries_per_scene)
        scene.matching_keywords = keywords
        self.store.put(project)
        return keywords

    async def _smart_keywords_or_fallback(
        self,
        project: VideoDesignProject,
        scene: ScenePlan,
        limit: int,
    ) -> tuple[list[str], dict | None]:
        try:
            keywords = await self.script_client.generate_search_keywords(
                voiceover_text=scene.voiceover_text,
                visual_brief=scene.visual_brief,
                on_screen_text=scene.on_screen_text,
                language=project.language,
            )
            normalized = _normalize_keywords(keywords, limit)
            if normalized:
                scene.matching_keywords = normalized
                self.store.put(project)
                return normalized, None
        except VideoDesignError as error:
            fallback = _fallback_keywords_for_scene(project, scene, limit)
            scene.matching_keywords = fallback
            self.store.put(project)
            return fallback, error.to_payload()
        except Exception as exc:
            fallback = _fallback_keywords_for_scene(project, scene, limit)
            scene.matching_keywords = fallback
            self.store.put(project)
            return fallback, {"code": SCRIPT_GENERATION_FAILED, "message": str(exc), "retryable": True}
        fallback = _fallback_keywords_for_scene(project, scene, limit)
        scene.matching_keywords = fallback
        self.store.put(project)
        return fallback, {
            "code": SCRIPT_GENERATION_FAILED,
            "message": "DeepSeek did not return usable search keywords.",
            "retryable": True,
        }

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
            layers=["media_base", "overlay_default", "caption_default", "text_overlay", "icon", "voiceover_audio", "background_audio", "transition_out"],
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

    def smooth_preview_file_path(self, project_id: str) -> Path:
        project = self.store.get(project_id)
        if project.smooth_preview.status not in {"ready", "stale"} or not project.smooth_preview.preview_path:
            raise VideoDesignError(PREVIEW_RENDER_FAILED, "Smooth preview has not been rendered yet.", retryable=True)
        path = Path(project.smooth_preview.preview_path)
        if not path.exists():
            raise VideoDesignError(PREVIEW_RENDER_FAILED, "Smooth preview file does not exist.", retryable=True)
        return path

    def material_file_path(self, project_id: str, asset_id: str) -> str:
        project = self.store.get(project_id)
        asset = _asset(project, asset_id)
        return asset.local_path

    def material_proxy_path(self, project_id: str, asset_id: str) -> str:
        project = self.store.get(project_id)
        asset = _asset(project, asset_id)
        return asset.proxy_path or asset.local_path

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
        project.timeline.items = [item for item in project.timeline.items if item.item_id != item_id]
        if len(project.timeline.items) == before:
            raise VideoDesignError(SCENE_NOT_FOUND, "Timeline item does not exist.")
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


def _selected_scenes(project: VideoDesignProject, scene_ids: list[str] | None) -> list[ScenePlan]:
    if not scene_ids:
        return project.scenes
    selected = [scene for scene in project.scenes if scene.scene_id in scene_ids]
    if len(selected) != len(scene_ids):
        raise VideoDesignError(SCENE_NOT_FOUND, "One or more scenes do not exist.")
    return selected


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


def _scene(project: VideoDesignProject, scene_id: str) -> ScenePlan:
    for scene in project.scenes:
        if scene.scene_id == scene_id:
            return scene
    raise VideoDesignError(SCENE_NOT_FOUND, "Scene does not exist.")


def _normalize_keywords(keywords, limit: int) -> list[str]:
    normalized = []
    for keyword in keywords or []:
        value = re.sub(r"\s+", " ", str(keyword)).strip(" ,.;:-")
        if not value or value.lower() in {item.lower() for item in normalized}:
            continue
        normalized.append(value[:120])
        if len(normalized) >= max(1, limit):
            break
    return normalized


def _fallback_keywords_for_scene(project: VideoDesignProject, scene: ScenePlan, limit: int) -> list[str]:
    candidates = []
    for text in (scene.visual_brief, scene.on_screen_text, scene.voiceover_text, project.idea, project.script):
        phrase = _keyword_phrase(text)
        if phrase:
            _append_keyword(candidates, phrase)
            if "video" not in phrase and "footage" not in phrase:
                _append_keyword(candidates, f"{phrase} raw footage")
        if len(candidates) >= max(1, limit):
            break
    return candidates[: max(1, limit)] or ["raw vertical footage"]


def _keyword_phrase(text: str | None) -> str:
    words = []
    for word in re.findall(r"[A-Za-z0-9]+", text or ""):
        value = word.lower()
        if len(value) < 3 or value in KEYWORD_STOPWORDS or value in words:
            continue
        words.append(value)
        if len(words) >= 4:
            break
    return " ".join(words)


def _append_keyword(keywords: list[str], keyword: str) -> None:
    if keyword and keyword.lower() not in {item.lower() for item in keywords}:
        keywords.append(keyword)


def _candidate(project: VideoDesignProject, candidate_id: str | None) -> MediaCandidate:
    for candidate in project.candidates:
        if candidate.candidate_id == candidate_id:
            return candidate
    raise VideoDesignError(CANDIDATE_NOT_FOUND, "Candidate does not exist.")


def _approved_candidate_for_scene(project: VideoDesignProject, scene: ScenePlan) -> MediaCandidate | None:
    if not scene.selected_candidate_id:
        return None
    try:
        candidate = _candidate(project, scene.selected_candidate_id)
    except VideoDesignError:
        return None
    if candidate.scene_id != scene.scene_id or candidate.status != "approved":
        return None
    return candidate


def _asset(project: VideoDesignProject, asset_id: str) -> MaterialAsset:
    for asset in project.material_assets:
        if asset.asset_id == asset_id:
            return asset
    raise VideoDesignError(DOWNLOAD_FAILED, "Material asset does not exist.")


def _candidates_for_scene(project: VideoDesignProject, scene_id: str, source: str | None = None) -> list[MediaCandidate]:
    return [
        candidate
        for candidate in project.candidates
        if candidate.scene_id == scene_id
        and candidate.status != "rejected"
        and (source is None or candidate.source == source)
    ]


def _add_candidates(project: VideoDesignProject, scene: ScenePlan, results, limit: int, source: str, keyword: str) -> list[str]:
    existing = {
        (candidate.source, candidate.source_result_id or candidate.douyin_result_id)
        for candidate in project.candidates
        if candidate.scene_id == scene.scene_id
    }
    candidate_ids = []
    for result in results:
        if (source, result.result_id) in existing:
            continue
        candidate = _candidate_from_public_result(scene, result, len(project.candidates) + 1, source, keyword)
        project.candidates.append(candidate)
        candidate_ids.append(candidate.candidate_id)
        if len(candidate_ids) >= limit:
            break
    return candidate_ids


def _candidate_from_public_result(
    scene: ScenePlan,
    result,
    index: int,
    source: str = "douyinsearch",
    keyword: str = "",
) -> MediaCandidate:
    source_item_id = str(getattr(result, "douyin_aweme_id", "") or getattr(result, "pin_id", "") or "")
    title = result.title or result.description or source_item_id
    duration = float(getattr(result, "duration", 0) or 0)
    douyin_aweme_id = source_item_id if source == "douyinsearch" else ""
    remote_stream_url = ""
    remote_download_url = ""
    if source == "douyinsearch":
        stored_result = douyin_service.store.get(result.result_id)
        if stored_result:
            remote_stream_url = stored_result.stream_remote_url
            remote_download_url = no_watermark_url_from_result(stored_result)
    return MediaCandidate(
        candidate_id=f"cand_{uuid.uuid4().hex}",
        source=source,
        scene_id=scene.scene_id,
        source_result_id=result.result_id,
        source_item_id=source_item_id,
        source_url=str(getattr(result, "source_url", "") or ""),
        search_keyword=keyword,
        douyin_result_id=result.result_id if source == "douyinsearch" else "",
        douyin_aweme_id=douyin_aweme_id,
        title=title,
        cover_url=result.cover_url,
        stream_url=result.stream_url,
        media_url=str(getattr(result, "media_url", "") or ""),
        download_url=result.download_url,
        remote_stream_url=remote_stream_url,
        remote_download_url=remote_download_url,
        duration=duration,
        match_reason=f"{source_label(source)} result {index} for scene {scene.order}.",
    )


def _search_errors_for_scene(project: VideoDesignProject, scene_id: str) -> list[dict]:
    errors = []
    for task in project.search_tasks:
        if task.scene_id != scene_id or not task.error:
            continue
        errors.append(
            {
                "source": task.source,
                "keyword": task.keyword,
                "code": task.error.get("code", "MATERIAL_SEARCH_FAILED"),
                "message": task.error.get("message", ""),
                "retryable": bool(task.error.get("retryable", False)),
            }
        )
    return errors


def _download_source_url(candidate: MediaCandidate) -> str:
    if _is_http_url(candidate.source_url):
        return candidate.source_url
    if candidate.source == "pinterestsearch" and candidate.source_item_id:
        return f"https://www.pinterest.com/pin/{candidate.source_item_id}/"
    aweme_id = candidate.douyin_aweme_id or candidate.source_item_id
    if candidate.source == "douyinsearch" and aweme_id:
        return f"https://www.douyin.com/video/{aweme_id}"
    return ""


def _cookie_file_for_source(source: str) -> Path | None:
    if source == "pinterestsearch":
        return pinterest_settings.cookie_file
    if source == "douyinsearch":
        return douyin_settings.cookie_file
    return None


def _cookie_header_for_source(source: str) -> str:
    cookie_file = _cookie_file_for_source(source)
    if not cookie_file or not cookie_file.exists():
        return ""
    if source == "pinterestsearch":
        return pinterest_cookie_header_from_file(cookie_file)
    if source == "douyinsearch":
        return douyin_cookie_header_from_file(cookie_file)
    return ""


def _is_blob_url(url: str) -> bool:
    return str(url or "").lower().startswith("blob:")


def _is_http_url(url: str) -> bool:
    parsed = urlparse(url or "")
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def source_label(source: str) -> str:
    return {
        "douyinsearch": "Douyin",
        "pinterestsearch": "Pinterest",
    }.get(source, source)


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


def _smooth_preview_url(project_id: str, updated_at: str) -> str:
    cache_key = re.sub(r"[^0-9A-Za-z]", "", updated_at) or uuid.uuid4().hex
    return f"/api/videodesign/projects/{project_id}/preview/file?v={cache_key}"


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
    command.extend(["-filter_complex", ";".join(filter_parts), "-map", f"[{chain}]"])
    if audio_input_index is not None:
        command.extend(["-map", f"{audio_input_index}:a:0", "-c:a", "aac", "-b:a", "160k"])
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


async def _create_preview_proxy(asset: MaterialAsset, aspect_ratio: str) -> Path | None:
    ffmpeg = shutil.which("ffmpeg")
    input_path = Path(asset.local_path)
    if not ffmpeg or not input_path.exists():
        return None
    width, height = _proxy_resolution(aspect_ratio)
    output_dir = settings.storage_dir / asset.project_id / "proxies"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{asset.asset_id}.mp4"
    temp_path = output_path.with_suffix(".tmp.mp4")
    if temp_path.exists():
        temp_path.unlink()
    vf = f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},fps=30"
    process = await asyncio.create_subprocess_exec(
        ffmpeg,
        "-y",
        "-i",
        str(input_path),
        "-an",
        "-vf",
        vf,
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "24",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        "-g",
        "60",
        str(temp_path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        await asyncio.wait_for(process.communicate(), timeout=180)
    except asyncio.TimeoutError:
        process.kill()
        await process.communicate()
        if temp_path.exists():
            temp_path.unlink()
        return None
    if process.returncode != 0 or not temp_path.exists():
        if temp_path.exists():
            temp_path.unlink()
        return None
    if output_path.exists():
        output_path.unlink()
    temp_path.replace(output_path)
    return output_path


async def _ensure_preview_proxy(asset: MaterialAsset, aspect_ratio: str) -> Path | None:
    if asset.proxy_path and Path(asset.proxy_path).exists():
        return Path(asset.proxy_path)
    proxy_path = await _create_preview_proxy(asset, aspect_ratio)
    if proxy_path:
        asset.proxy_path = str(proxy_path)
    return proxy_path


def _proxy_resolution(aspect_ratio: str) -> tuple[int, int]:
    if aspect_ratio == "16:9":
        return 1920, 1080
    if aspect_ratio == "1:1":
        return 1080, 1080
    return 1080, 1920


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
        "overlay": "overlay_default",
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
    transition_pack_id = extras.get("transition_pack_id") or "fade"
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
                matching_keywords=[str(keyword) for keyword in item.get("search_keywords", [])][:3] or [voiceover[:80]],
                duration_seconds=max(split_settings.min_scene_duration_seconds, min(split_settings.max_scene_duration_seconds, duration)),
                template_scene_id="auto",
            )
        )
    return refresh_scene_orders(scenes)


videodesign_service = VideoDesignService()
