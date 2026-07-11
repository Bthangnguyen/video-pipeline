from app.videodesign.errors import SCENE_NOT_FOUND, VideoDesignError
from app.videodesign.schemas import ScenePlan, VideoDesignProject


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
