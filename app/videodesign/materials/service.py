import asyncio
import uuid
from pathlib import Path

from app.douyinsearch.errors import DouyinSearchError
from app.douyinsearch.schemas import SearchRequest
from app.douyinsearch.service import douyin_service
from app.pinterestsearch.errors import PinterestSearchError
from app.pinterestsearch.schemas import SearchRequest as PinterestSearchRequest
from app.pinterestsearch.service import pinterest_service
from app.videodesign.errors import (
    CANDIDATE_NOT_FOUND,
    DOWNLOAD_FAILED,
    MATERIAL_SEARCH_FAILED,
    MATERIAL_SEARCH_TIMEOUT,
    SCENE_NOT_READY,
    SCRIPT_GENERATION_FAILED,
    VideoDesignError,
)
from app.videodesign.materials.candidates import (
    _add_group_candidates,
    _approved_candidate_for_scene,
    _asset,
    _candidate,
    _candidate_from_public_result,
    _candidates_for_scene,
    _cookie_file_for_source,
    _cookie_header_for_source,
    _download_source_url,
    _is_blob_url,
    _material_asset_from_candidate,
    _material_output_path,
    _recover_candidate_for_existing_material,
    _recover_existing_material_asset,
    _search_errors_for_scene,
    source_label,
)
from app.videodesign.materials.proxy import _ensure_preview_proxy
from app.videodesign.materials.search_plan import (
    _ensure_material_search_plan,
    _fallback_material_search_plan,
    _fallback_visual_search_plan,
    _keywords_for_search_group,
    _legacy_keywords_from_visual_plan,
    _material_search_plan_from_scene_plans,
    _merge_generated_material_search_plan,
    _normalize_generated_material_search_plan,
    _normalize_user_material_search_plan,
    _normalize_visual_search_plan,
    _search_groups_for_request,
    _should_translate_douyin_keyword,
    _sync_scene_group_ids,
    _sync_scenes_from_material_search_plan,
)
from app.videodesign.project_state import _scene, _selected_scenes
from app.videodesign.schemas import (
    DouyinSearchTask,
    KeywordGenerateRequest,
    MaterialSearchPlan,
    MaterialsDownloadRequest,
    MaterialsPreflightRequest,
    MaterialsPruneRequest,
    MaterialsSearchRequest,
    MediaCandidate,
    ScenePlan,
    SceneSelectionRequest,
    VideoDesignProject,
)


class MaterialsService:
    def __init__(self, store, script_client, ytdlp):
        self.store = store
        self.script_client = script_client
        self.ytdlp = ytdlp
        self.download_candidate = self._download_candidate_impl
        self.ensure_preview_proxy = _ensure_preview_proxy

    async def generate_scene_keywords(self, project_id: str, request: KeywordGenerateRequest) -> dict:
        project = self.store.get(project_id)
        scenes = _selected_scenes(project, request.scene_ids)
        total = len(scenes)
        self._set_progress(project, "keyword_generation", "Planning shared search groups for all selected scenes.", 0, total)
        plans, errors = await self._generate_visual_plans_or_fallback(project, scenes)
        for index, scene in enumerate(scenes, start=1):
            plan = plans[scene.scene_id]
            self._set_progress(
                project,
                "keyword_generation",
                f"Assigned scene {index}/{total} to {plan.get('search_role', 'base')}: Douyin {plan.get('douyin_primary_keyword', '')} / Pinterest {plan.get('pinterest_primary_keyword', '')}",
                index,
                total,
                {
                    "scene_id": scene.scene_id,
                    "search_group_id": scene.search_group_id,
                    "fallback": str(plan.get("query_strategy", "")).startswith("fallback"),
                },
            )
        self.store.put(project)
        self._set_progress(project, "idle", "Keyword generation finished.", total, total)
        return {
            "success": True,
            "project_id": project.project_id,
            "scenes": [scene.model_dump() for scene in scenes],
            "search_plan": project.material_search_plan.model_dump(),
            "errors": errors,
        }


    def set_material_search_plan(self, project_id: str, request: MaterialSearchPlan) -> dict:
        project = self.store.get(project_id)
        project.material_search_plan = _normalize_user_material_search_plan(project, request)
        _sync_scenes_from_material_search_plan(project)
        self.store.put(project)
        return {
            "success": True,
            "project_id": project.project_id,
            "search_plan": project.material_search_plan.model_dump(),
            "scenes": [scene.model_dump() for scene in project.scenes],
        }


    async def search_materials(self, project_id: str, request: MaterialsSearchRequest) -> dict:
        project = self.store.get(project_id)
        requested_scenes = _selected_scenes(project, request.scene_ids)
        total = len(requested_scenes)
        douyin_limit = request.douyin_min_per_scene if request.douyin_min_per_scene is not None else request.candidates_per_scene
        pinterest_limit = request.pinterest_min_per_scene
        self._set_progress(project, "materials_search", "Preparing shared material search groups.", 0, total)

        if request.use_smart_keywords:
            self._set_progress(project, "materials_search", "Regenerating one shared search plan for all selected scenes.", 0, total)
            await self._generate_visual_plans_or_fallback(project, requested_scenes)

        _ensure_material_search_plan(project, requested_scenes)
        if request.popular_first is not None:
            project.material_search_plan.popular_first = request.popular_first
        popular_first = project.material_search_plan.popular_first
        groups = _search_groups_for_request(project, request)
        selected_group_ids = {group.group_id for group in groups}
        scenes = [
            scene
            for scene in project.scenes
            if any(scene.scene_id in group.scene_ids for group in groups)
        ]
        scene_ids = {scene.scene_id for scene in scenes}
        project.search_tasks = [
            task
            for task in project.search_tasks
            if task.search_group_id not in selected_group_ids
            and not (not task.search_group_id and task.scene_id in scene_ids)
        ]
        for scene in scenes:
            scene.search_tasks = []

        plans = []
        for index, group in enumerate(groups, start=1):
            group_scenes = [scene for scene in project.scenes if scene.scene_id in group.scene_ids]
            for scene in group_scenes:
                scene.approval_state = "searching"
            source_plan = [
                ("douyinsearch", douyin_limit),
                ("pinterestsearch", pinterest_limit),
            ]
            for source, source_limit in source_plan:
                if source_limit <= 0:
                    continue
                if all(len(_candidates_for_scene(project, scene.scene_id, source)) >= source_limit for scene in group_scenes):
                    continue
                keywords = _keywords_for_search_group(group, source, request.queries_per_scene)
                plans.append(
                    {
                        "index": index,
                        "group": group,
                        "scenes": group_scenes,
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
            self._set_progress(project, "idle", "Shared material search finished.", len(groups), len(groups))
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
            group = plan["group"]
            group_scenes = plan["scenes"]
            source = plan["source"]
            async with semaphores[source]:
                for keyword in plan["keywords"]:
                    missing_counts = [
                        max(0, plan["source_limit"] - len(_candidates_for_scene(project, scene.scene_id, source)))
                        for scene in group_scenes
                    ]
                    needed = max(missing_counts, default=0)
                    if needed <= 0:
                        break
                    task = DouyinSearchTask(
                        search_task_id=f"dst_{uuid.uuid4().hex}",
                        project_id=project.project_id,
                        scene_id=group_scenes[0].scene_id,
                        search_group_id=group.group_id,
                        source=source,
                        keyword=keyword,
                        translate_to_chinese=_should_translate_douyin_keyword(keyword, request.translate_to_chinese) if source == "douyinsearch" else False,
                        limit=max(needed, 3),
                        status="searching",
                    )
                    async with lock:
                        project.search_tasks.append(task)
                        for scene in group_scenes:
                            scene.search_tasks.append(task.search_task_id)
                        self._set_progress(
                            project,
                            "materials_search",
                            f"Searching {source_label(source)} group {plan['index']}/{len(groups)} ({group.label}): {keyword}",
                            completed,
                            progress_total,
                            {
                                "search_group_id": group.group_id,
                                "scene_ids": group.scene_ids,
                                "keyword": keyword,
                                "source": source,
                                "popular_first": popular_first,
                            },
                        )
                        self.store.put(project)
                    try:
                        if source == "douyinsearch":
                            translate_keyword = _should_translate_douyin_keyword(keyword, request.translate_to_chinese)
                            response = await asyncio.wait_for(
                                douyin_service.search(
                                    SearchRequest(
                                        keyword=keyword,
                                        translate_to_chinese=translate_keyword,
                                        limit=max(needed, 3),
                                        strategy="auto",
                                        popular_first=popular_first,
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
                            candidate_ids = _add_group_candidates(
                                project,
                                group,
                                group_scenes,
                                response.items,
                                plan["source_limit"],
                                source,
                                keyword,
                                response.diagnostics,
                                popular_first,
                            )
                            task.status = "completed"
                            task.candidate_ids.extend(candidate_ids)
                            if candidate_ids:
                                for scene in group_scenes:
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
                    f"Finished {source_label(source)} group {plan['index']}/{len(groups)} ({group.label}).",
                    completed,
                    progress_total,
                    {
                        "search_group_id": group.group_id,
                        "scene_ids": group.scene_ids,
                        "source": source,
                    },
                )
                self.store.put(project)

        await asyncio.gather(*(run_plan(plan) for plan in plans))
        for scene in scenes:
            scene.approval_state = "needs_review" if _candidates_for_scene(project, scene.scene_id) else "planned"
        self.store.put(project)
        self._set_progress(project, "idle", "Shared material search finished.", progress_total, progress_total)
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
        return {
            "success": True,
            "project_id": project.project_id,
            "search_plan": project.material_search_plan.model_dump(),
            "rows": rows,
        }


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
        total = len(scenes)
        self._set_progress(project, "materials_download", "Preparing approved video downloads.", 0, total)
        for index, scene in enumerate(scenes, start=1):
            if scene.material_asset_id and not request.force:
                asset = _asset(project, scene.material_asset_id)
                await self.ensure_preview_proxy(asset, project.aspect_ratio)
                downloaded.append(asset.model_dump())
                self._set_progress(
                    project,
                    "materials_download",
                    f"Scene {index}/{total} already has downloaded material.",
                    index,
                    total,
                    {"scene_id": scene.scene_id, "asset_id": asset.asset_id},
                )
                continue
            output_path = _material_output_path(project, scene)
            candidate = _approved_candidate_for_scene(project, scene)
            if not candidate and not request.force:
                candidate = _recover_candidate_for_existing_material(project, scene, output_path)
            existing_asset = None if request.force else _recover_existing_material_asset(project, scene, candidate, output_path)
            if existing_asset:
                await self.ensure_preview_proxy(existing_asset, project.aspect_ratio)
                downloaded.append(existing_asset.model_dump())
                self._set_progress(
                    project,
                    "materials_download",
                    f"Recovered existing scene {index}/{total} material file.",
                    index,
                    total,
                    {"scene_id": scene.scene_id, "asset_id": existing_asset.asset_id},
                )
                continue
            if not candidate:
                skipped.append({"scene_id": scene.scene_id, "code": SCENE_NOT_READY, "message": "Scene has no approved candidate."})
                self._set_progress(
                    project,
                    "materials_download",
                    f"Skipped scene {index}/{total}: no approved candidate.",
                    index,
                    total,
                    {"scene_id": scene.scene_id},
                )
                continue
            scene.approval_state = "download_pending"
            self._set_progress(
                project,
                "materials_download",
                f"Downloading scene {index}/{total}.",
                index - 1,
                total,
                {"scene_id": scene.scene_id, "candidate_id": candidate.candidate_id, "source": candidate.source},
            )
            try:
                await self.download_candidate(candidate, output_path)
            except Exception as exc:
                scene.approval_state = "approved"
                self._set_progress(
                    project,
                    "materials_download_failed",
                    f"Download failed at scene {index}/{total}: {exc}",
                    index - 1,
                    total,
                    {"scene_id": scene.scene_id, "candidate_id": candidate.candidate_id, "source": candidate.source},
                )
                raise VideoDesignError(DOWNLOAD_FAILED, f"Could not download approved video: {exc}", retryable=True) from exc
            asset = _material_asset_from_candidate(project, scene, candidate, output_path)
            await self.ensure_preview_proxy(asset, project.aspect_ratio)
            project.material_assets.append(asset)
            scene.material_asset_id = asset.asset_id
            scene.clip = None
            scene.approval_state = "downloaded"
            downloaded.append(asset.model_dump())
            self._set_progress(
                project,
                "materials_download",
                f"Downloaded scene {index}/{total}.",
                index,
                total,
                {"scene_id": scene.scene_id, "asset_id": asset.asset_id},
            )
        self._set_progress(project, "idle", f"Downloaded {len(downloaded)} material file(s).", total, total)
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


    async def _download_candidate_impl(self, candidate: MediaCandidate, output_path: Path) -> None:
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


    async def _generate_visual_plans_or_fallback(
        self,
        project: VideoDesignProject,
        scenes: list[ScenePlan],
    ) -> tuple[dict[str, dict], list[dict]]:
        plans: dict[str, dict] = {}
        errors: list[dict] = []
        try:
            data = await self.script_client.generate_visual_search_keywords(
                project_idea=project.idea,
                full_script=project.script,
                scenes=[
                    {
                        "scene_id": scene.scene_id,
                        "order": scene.order,
                        "voiceover_text": scene.voiceover_text,
                        "on_screen_text": scene.on_screen_text,
                        "visual_brief": scene.visual_brief,
                    }
                    for scene in scenes
                ],
                language=project.language,
                target_style=str(project.design_preset.get("scene_media", {}).get("style", "mixed")),
            )
            if isinstance(data.get("groups"), list):
                generated_plan, plan_errors = _normalize_generated_material_search_plan(project, scenes, data)
                errors.extend(plan_errors)
                project.material_search_plan = _merge_generated_material_search_plan(project, scenes, generated_plan)
                _sync_scenes_from_material_search_plan(project)
                plans = {scene.scene_id: scene.visual_search_plan for scene in scenes}
            else:
                for scene in scenes:
                    plan = _normalize_visual_search_plan(data, project, scene)
                    if not plan:
                        plan = _fallback_visual_search_plan(project, scene)
                        errors.append(
                            {
                                "scene_id": scene.scene_id,
                                "error": {
                                    "code": SCRIPT_GENERATION_FAILED,
                                    "message": "DeepSeek did not return a usable visual search plan for this scene.",
                                    "retryable": True,
                                },
                            }
                        )
                    elif plan.get("query_strategy") == "fallback_ungrounded":
                        errors.append(
                            {
                                "scene_id": scene.scene_id,
                                "error": {
                                    "code": SCRIPT_GENERATION_FAILED,
                                    "message": "DeepSeek returned an ungrounded visual query, so a broad local fallback was used.",
                                    "retryable": True,
                                },
                            }
                        )
                    scene.visual_search_plan = plan
                    scene.matching_keywords = _legacy_keywords_from_visual_plan(plan, 1)
                    plans[scene.scene_id] = plan
                generated_plan = _material_search_plan_from_scene_plans(project, scenes)
                project.material_search_plan = _merge_generated_material_search_plan(project, scenes, generated_plan)
                _sync_scene_group_ids(project, preserve_visual_plans=True)
        except VideoDesignError as error:
            fallback_plan = _fallback_material_search_plan(project, scenes)
            project.material_search_plan = _merge_generated_material_search_plan(project, scenes, fallback_plan)
            _sync_scenes_from_material_search_plan(project, query_strategy="fallback_local")
            for scene in scenes:
                plans[scene.scene_id] = scene.visual_search_plan
                errors.append({"scene_id": scene.scene_id, "error": error.to_payload()})
        except Exception as exc:
            fallback_plan = _fallback_material_search_plan(project, scenes)
            project.material_search_plan = _merge_generated_material_search_plan(project, scenes, fallback_plan)
            _sync_scenes_from_material_search_plan(project, query_strategy="fallback_local")
            for scene in scenes:
                plans[scene.scene_id] = scene.visual_search_plan
                errors.append(
                    {
                        "scene_id": scene.scene_id,
                        "error": {"code": SCRIPT_GENERATION_FAILED, "message": str(exc), "retryable": True},
                    }
                )
        self.store.put(project)
        return plans, errors


    def material_file_path(self, project_id: str, asset_id: str) -> str:
        project = self.store.get(project_id)
        asset = _asset(project, asset_id)
        return asset.local_path


    def material_proxy_path(self, project_id: str, asset_id: str) -> str:
        project = self.store.get(project_id)
        asset = _asset(project, asset_id)
        return asset.proxy_path or asset.local_path


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
