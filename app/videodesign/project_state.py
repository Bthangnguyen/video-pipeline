from pathlib import Path

from app.videodesign.config import settings
from app.videodesign.errors import SCENE_NOT_FOUND, VideoDesignError
from app.videodesign.schemas import ScenePlan, SmoothPreview, VideoDesignProject


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


def _renderable_scenes(project: VideoDesignProject) -> list[ScenePlan]:
    return [scene for scene in project.scenes if scene.approval_state != "placeholder_allowed"]


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
