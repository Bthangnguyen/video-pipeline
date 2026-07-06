import asyncio
import uuid
from datetime import datetime, timezone

from app.douyinsearch.errors import DouyinSearchError
from app.douyinsearch.schemas import SearchRequest
from app.douyinsearch.service import douyin_service
from app.videodesign.config import settings
from app.videodesign.errors import (
    CANDIDATE_NOT_FOUND,
    DOWNLOAD_FAILED,
    INVALID_PROJECT_INPUT,
    MATERIAL_SEARCH_FAILED,
    MATERIAL_SEARCH_TIMEOUT,
    SCENE_NOT_FOUND,
    SCENE_NOT_READY,
    SCRIPT_REQUIRED,
    VideoDesignError,
)
from app.videodesign.planner import estimate_duration, make_caption_chunks, refresh_scene_orders, split_script
from app.videodesign.schemas import (
    CreateProjectRequest,
    DouyinSearchTask,
    MaterialsDownloadRequest,
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


class VideoDesignService:
    def __init__(self):
        self.store = VideoDesignStore()
        self.script_client = DeepSeekScriptClient()
        self.tts_client = TTSClient()

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

    async def search_materials(self, project_id: str, request: MaterialsSearchRequest) -> dict:
        project = self.store.get(project_id)
        scenes = _selected_scenes(project, request.scene_ids)
        total = len(scenes)
        self._set_progress(project, "materials_search", "Starting Douyin material search.", 0, total)
        for index, scene in enumerate(scenes, start=1):
            scene.approval_state = "searching"
            for keyword in scene.matching_keywords[: request.queries_per_scene]:
                self._set_progress(
                    project,
                    "materials_search",
                    f"Searching scene {index}/{total}: {keyword}",
                    index - 1,
                    total,
                    {"scene_id": scene.scene_id, "keyword": keyword},
                )
                task = DouyinSearchTask(
                    search_task_id=f"dst_{uuid.uuid4().hex}",
                    project_id=project.project_id,
                    scene_id=scene.scene_id,
                    keyword=keyword,
                    translate_to_chinese=request.translate_to_chinese,
                    limit=max(request.candidates_per_scene, 3),
                    status="searching",
                )
                project.search_tasks.append(task)
                scene.search_tasks.append(task.search_task_id)
                try:
                    search_request = SearchRequest(
                        keyword=keyword,
                        translate_to_chinese=request.translate_to_chinese,
                        limit=max(request.candidates_per_scene, 3),
                        strategy="auto",
                    )
                    response = await asyncio.wait_for(
                        douyin_service.search(search_request),
                        timeout=60,
                    )
                    task.status = "completed"
                    candidate_ids = _add_candidates(project, scene, response.items, request.candidates_per_scene)
                    task.candidate_ids.extend(candidate_ids)
                except asyncio.TimeoutError:
                    task.status = "failed"
                    task.error = {
                        "code": MATERIAL_SEARCH_TIMEOUT,
                        "message": f"Douyin search timed out for keyword '{keyword}'.",
                        "retryable": True,
                    }
                except DouyinSearchError as error:
                    task.status = "failed"
                    task.error = error.to_payload()
                except Exception as exc:
                    task.status = "failed"
                    task.error = {"code": MATERIAL_SEARCH_FAILED, "message": str(exc), "retryable": True}
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
        self._set_progress(project, "idle", "Douyin material search finished.", total, total)
        return self.review(project_id)

    def review(self, project_id: str) -> dict:
        project = self.store.get(project_id)
        rows = []
        for scene in project.scenes:
            candidates = _candidates_for_scene(project, scene.scene_id)
            rows.append({"scene": scene.model_dump(), "candidates": [candidate.model_dump() for candidate in candidates]})
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
            result = douyin_service.store.get(candidate.douyin_result_id)
            if not result:
                raise VideoDesignError(DOWNLOAD_FAILED, f"Douyin result expired for scene {scene.scene_id}.", retryable=True)
            scene.approval_state = "download_pending"
            asset_id = f"mat_{uuid.uuid4().hex}"
            output_path = settings.storage_dir / project.project_id / "materials" / f"{scene.scene_id}.mp4"
            try:
                await douyin_service.stream_proxy.download_to_file(result, output_path)
            except Exception as exc:
                scene.approval_state = "needs_review"
                raise VideoDesignError(DOWNLOAD_FAILED, f"Could not download approved video: {exc}", retryable=True) from exc
            asset = MaterialAsset(
                asset_id=asset_id,
                project_id=project.project_id,
                scene_id=scene.scene_id,
                candidate_id=candidate.candidate_id,
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

    def create_studio_timeline(self, project_id: str) -> dict:
        project = self.store.get(project_id)
        items: list[TimelineItem] = []
        current = 0.0
        for scene in project.scenes:
            if scene.approval_state == "placeholder_allowed":
                continue
            if not scene.material_asset_id:
                raise VideoDesignError(SCENE_NOT_READY, f"Scene {scene.scene_id} must be downloaded before studio.")
            duration = scene.duration_seconds or estimate_duration(scene.voiceover_text)
            end = round(current + duration, 2)
            items.extend(_timeline_items_for_scene(project.project_id, scene, current, end))
            current = end
        timeline = TimelineDraft(
            timeline_id=f"tln_{uuid.uuid4().hex}",
            project_id=project.project_id,
            duration_seconds=round(current, 2),
            aspect_ratio=project.aspect_ratio,
            scenes=[scene.scene_id for scene in project.scenes],
            layers=["media_base", "voiceover_audio", "caption_default", "text_overlay", "transition_out"],
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


def _candidates_for_scene(project: VideoDesignProject, scene_id: str) -> list[MediaCandidate]:
    return [candidate for candidate in project.candidates if candidate.scene_id == scene_id and candidate.status != "rejected"]


def _add_candidates(project: VideoDesignProject, scene: ScenePlan, results, limit: int) -> list[str]:
    existing = {candidate.douyin_result_id for candidate in project.candidates if candidate.scene_id == scene.scene_id}
    candidate_ids = []
    for result in results:
        if result.result_id in existing:
            continue
        candidate = _candidate_from_public_result(scene, result, len(project.candidates) + 1)
        project.candidates.append(candidate)
        candidate_ids.append(candidate.candidate_id)
        if len(candidate_ids) >= limit:
            break
    return candidate_ids


def _candidate_from_public_result(scene: ScenePlan, result, index: int) -> MediaCandidate:
    title = result.title or result.description or result.douyin_aweme_id
    score = _score_candidate(scene, title, result.duration)
    return MediaCandidate(
        candidate_id=f"cand_{uuid.uuid4().hex}",
        scene_id=scene.scene_id,
        douyin_result_id=result.result_id,
        douyin_aweme_id=result.douyin_aweme_id,
        title=title,
        cover_url=result.cover_url,
        stream_url=result.stream_url,
        download_url=result.download_url,
        duration=result.duration,
        score=score,
        match_reason=f"Candidate {index} matches query terms for scene {scene.order}.",
    )


def _score_candidate(scene: ScenePlan, title: str, duration: float) -> float:
    text = title.lower()
    keyword_hits = sum(1 for keyword in scene.matching_keywords[:1] for word in keyword.split() if word.lower() in text)
    duration_fit = 1.0 if not duration or duration >= scene.duration_seconds else 0.6
    return round(min(1.0, 0.55 + keyword_hits * 0.08) * duration_fit, 2)


def _timeline_items_for_scene(project_id: str, scene: ScenePlan, start: float, end: float) -> list[TimelineItem]:
    duration = end - start
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
