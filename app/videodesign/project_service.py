import uuid
from datetime import datetime, timezone

from app.videodesign.errors import INVALID_PROJECT_INPUT, SCRIPT_REQUIRED, VideoDesignError
from app.videodesign.materials.search_plan import _normalize_keywords, _reset_material_search_plan
from app.videodesign.planner import estimate_duration, make_caption_chunks, refresh_scene_orders, split_script
from app.videodesign.project_state import _project_sort_value, _project_summary, _scene
from app.videodesign.schemas import (
    CreateProjectRequest,
    ScenePlan,
    ScriptGenerateRequest,
    SplitSettings,
    VideoDesignProject,
)


class ProjectService:
    def __init__(self, store, script_client):
        self.store = store
        self.script_client = script_client

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


    def progress(self, project_id: str) -> dict:
        project = self.store.get(project_id)
        return {"success": True, "project_id": project.project_id, "progress": project.progress.model_dump()}


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
