import asyncio
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from app.douyinsearch.config import settings as douyin_settings
from app.douyinsearch.cookies import cookie_header_from_file as douyin_cookie_header_from_file
from app.douyinsearch.errors import DouyinSearchError
from app.douyinsearch.schemas import SearchRequest
from app.douyinsearch.service import douyin_service
from app.pinterestsearch.config import settings as pinterest_settings
from app.pinterestsearch.cookies import cookie_header_from_file as pinterest_cookie_header_from_file
from app.pinterestsearch.errors import PinterestSearchError
from app.pinterestsearch.schemas import SearchRequest as PinterestSearchRequest
from app.pinterestsearch.service import pinterest_service
from app.videodesign.config import settings
from app.videodesign.downloader import YtDlpDownloader
from app.videodesign.errors import (
    CANDIDATE_NOT_FOUND,
    DOWNLOAD_FAILED,
    INVALID_PROJECT_INPUT,
    MATERIAL_SEARCH_FAILED,
    MATERIAL_SEARCH_TIMEOUT,
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
    MaterialsSearchRequest,
    MaterialAsset,
    MediaCandidate,
    ScenePlan,
    SceneSelectionRequest,
    ScriptGenerateRequest,
    SplitSettings,
    TTSGenerateRequest,
    TTSMeta,
    TimelineDraft,
    TimelineItem,
    TimelineItemPatch,
    VideoDesignProject,
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
        scenes = _selected_scenes(project, request.scene_ids)
        for scene in scenes:
            text = scene.tts_text or scene.voiceover_text
            result = await self.tts_client.generate(text, project.project_id, scene.scene_id, provider, voice_id)
            scene.duration_seconds = result.duration_seconds
            scene.caption_chunks = result.caption_chunks
            scene.tts = TTSMeta(
                provider=provider,
                voice_id=voice_id,
                audio_url=f"/api/videodesign/projects/{project.project_id}/scenes/{scene.scene_id}/audio",
                audio_path=str(result.audio_path),
                sync_state="synced",
            )
        self.store.put(project)
        return {"success": True, "scenes": [scene.model_dump() for scene in scenes]}

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
        self._set_progress(project, "materials_search", "Starting material search.", 0, total)
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
                for keyword in keywords[: request.queries_per_scene]:
                    existing_count = len(_candidates_for_scene(project, scene.scene_id, source))
                    if existing_count >= source_limit:
                        break
                    needed = source_limit - existing_count
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
                    project.search_tasks.append(task)
                    scene.search_tasks.append(task.search_task_id)
                    self._set_progress(
                        project,
                        "materials_search",
                        f"Searching {source_label(source)} scene {index}/{total}: {keyword}",
                        index - 1,
                        total,
                        {"scene_id": scene.scene_id, "keyword": keyword, "source": source},
                    )
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
                        task.status = "completed"
                        candidate_ids = _add_candidates(project, scene, response.items, needed, source, keyword)
                        task.candidate_ids.extend(candidate_ids)
                        if candidate_ids:
                            scene.approval_state = "needs_review"
                    except asyncio.TimeoutError:
                        task.status = "failed"
                        task.error = {
                            "code": MATERIAL_SEARCH_TIMEOUT,
                            "message": f"{source_label(source)} search timed out for keyword '{keyword}'.",
                            "retryable": True,
                        }
                    except (DouyinSearchError, PinterestSearchError) as error:
                        task.status = "failed"
                        task.error = error.to_payload()
                    except Exception as exc:
                        task.status = "failed"
                        task.error = {"code": MATERIAL_SEARCH_FAILED, "message": str(exc), "retryable": True}
                    finally:
                        self.store.put(project)
            scene.approval_state = "needs_review" if _candidates_for_scene(project, scene.scene_id) else "planned"
            self._set_progress(
                project,
                "materials_search",
                f"Finished scene {index}/{total}: {len(_candidates_for_scene(project, scene.scene_id))} candidates.",
                index,
                total,
                {"scene_id": scene.scene_id},
            )
        self.store.put(project)
        self._set_progress(project, "idle", "Material search finished.", total, total)
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
            candidate.status = "rejected"
            if scene.selected_candidate_id == candidate.candidate_id:
                scene.selected_candidate_id = None
            scene.approval_state = "needs_review"
        elif request.action == "approve":
            candidate = _candidate(project, request.candidate_id)
            candidate.status = "approved"
            scene.selected_candidate_id = candidate.candidate_id
            scene.approval_state = "approved"
        elif request.action == "manual_select":
            if not request.douyin_result_id:
                raise VideoDesignError(CANDIDATE_NOT_FOUND, "douyin_result_id is required for manual selection.")
            result = douyin_service.get_result(request.douyin_result_id)["item"]
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
        for scene in scenes:
            if scene.material_asset_id and not request.force:
                downloaded.append(_asset(project, scene.material_asset_id).model_dump())
                continue
            if scene.approval_state not in ("approved", "download_pending", "downloaded") or not scene.selected_candidate_id:
                raise VideoDesignError(SCENE_NOT_READY, f"Scene {scene.scene_id} has no approved candidate.")
            candidate = _candidate(project, scene.selected_candidate_id)
            scene.approval_state = "download_pending"
            asset_id = f"mat_{uuid.uuid4().hex}"
            output_path = settings.storage_dir / project.project_id / "materials" / f"{scene.scene_id}.mp4"
            try:
                await self._download_candidate(candidate, output_path)
            except Exception as exc:
                scene.approval_state = "needs_review"
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
            project.material_assets.append(asset)
            scene.material_asset_id = asset.asset_id
            scene.approval_state = "downloaded"
            downloaded.append(asset.model_dump())
        self.store.put(project)
        return {"success": True, "assets": downloaded}

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
                if not result:
                    raise VideoDesignError(DOWNLOAD_FAILED, "Douyin result expired.", retryable=True)
                await douyin_service.stream_proxy.download_to_file(result, output_path)
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

    def create_studio_timeline(self, project_id: str) -> dict:
        project = self.store.get(project_id)
        items: list[TimelineItem] = []
        current = 0.0
        renderable_scenes = [scene for scene in project.scenes if scene.approval_state != "placeholder_allowed"]
        for index, scene in enumerate(renderable_scenes):
            if scene.approval_state == "placeholder_allowed":
                continue
            if not scene.material_asset_id:
                raise VideoDesignError(SCENE_NOT_READY, f"Scene {scene.scene_id} must be downloaded before studio.")
            asset = _asset(project, scene.material_asset_id)
            duration = scene.duration_seconds or estimate_duration(scene.voiceover_text)
            end = round(current + duration, 2)
            items.extend(_timeline_items_for_scene(project.project_id, scene, asset, current, end, project.design_preset))
            if index < len(renderable_scenes) - 1:
                items.append(_transition_item_for_scene(scene, end, project.design_preset))
            current = end
        timeline = TimelineDraft(
            timeline_id=f"tln_{uuid.uuid4().hex}",
            project_id=project.project_id,
            duration_seconds=round(current, 2),
            aspect_ratio=project.aspect_ratio,
            scenes=[scene.scene_id for scene in project.scenes],
            layers=["media_base", "voiceover_audio", "caption_default", "text_overlay", "overlay_default", "transition_out"],
            items=items,
        )
        project.timeline = timeline
        self.store.put(project)
        return {"success": True, "timeline": timeline.model_dump()}

    def timeline(self, project_id: str) -> dict:
        project = self.store.get(project_id)
        return {"success": True, "timeline": project.timeline.model_dump() if project.timeline else None}

    def material_file_path(self, project_id: str, asset_id: str) -> str:
        project = self.store.get(project_id)
        asset = _asset(project, asset_id)
        return asset.local_path

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
                if patch.source_ref is not None:
                    item.source_ref = patch.source_ref
                if patch.transform is not None:
                    item.transform = patch.transform
                if patch.style is not None:
                    item.style = patch.style
                self.store.put(project)
                return {"success": True, "item": item.model_dump()}
        raise VideoDesignError(SCENE_NOT_FOUND, "Timeline item does not exist.")

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
        download_url=result.download_url,
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


def _timeline_items_for_scene(project_id: str, scene: ScenePlan, asset: MaterialAsset, start: float, end: float, preset: dict | None = None) -> list[TimelineItem]:
    duration = end - start
    extras = (preset or {}).get("extras", {})
    overlay_pack_id = extras.get("overlay_pack_id") or "caption_shadow"
    asset_duration = max(0.0, float(asset.duration or 0))
    trim_end = round(min(asset_duration or duration, duration), 2)
    items = [
        TimelineItem(
            item_id=f"itm_{uuid.uuid4().hex}",
            layer_id="media_base",
            scene_id=scene.scene_id,
            type="media",
            start_seconds=start,
            end_seconds=end,
            source_ref={
                "source": "material_asset",
                "asset_id": scene.material_asset_id,
                "media_url": f"/api/videodesign/projects/{project_id}/materials/{scene.material_asset_id}/file",
                "asset_duration_seconds": asset_duration,
                "timeline_duration_seconds": round(duration, 2),
                "trim_start_seconds": 0.0,
                "trim_end_seconds": trim_end,
                "cut_strategy": "scene_duration_from_start",
            },
            transform={"fit": "cover", "x": 50, "y": 50, "scale": 1, "rotation": 0},
        ),
        TimelineItem(
            item_id=f"itm_{uuid.uuid4().hex}",
            layer_id="caption_default",
            scene_id=scene.scene_id,
            type="caption",
            start_seconds=start,
            end_seconds=end,
            source_ref={"caption_chunks": [chunk.model_dump() for chunk in scene.caption_chunks]},
            style={"caption_style_id": "word_reveal_bold"},
        ),
        TimelineItem(
            item_id=f"itm_{uuid.uuid4().hex}",
            layer_id="text_overlay",
            scene_id=scene.scene_id,
            type="text",
            start_seconds=start,
            end_seconds=round(start + min(duration, 2.5), 2),
            source_ref={"text": scene.on_screen_text},
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
    transition_pack_id = extras.get("transition_pack_id") or "clean_cut"
    start = round(max(0, scene_end - 0.35), 2)
    return TimelineItem(
        item_id=f"itm_{uuid.uuid4().hex}",
        layer_id="transition_out",
        scene_id=scene.scene_id,
        type="transition",
        start_seconds=start,
        end_seconds=round(scene_end, 2),
        source_ref={"transition_pack_id": transition_pack_id},
        style={"transition_pack_id": transition_pack_id},
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
