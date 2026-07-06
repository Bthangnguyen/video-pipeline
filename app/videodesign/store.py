from pathlib import Path

from app.videodesign.config import settings
from app.videodesign.errors import PROJECT_NOT_FOUND, VideoDesignError
from app.videodesign.schemas import VideoDesignProject


class VideoDesignStore:
    def __init__(self):
        self._projects: dict[str, VideoDesignProject] = {}

    def put(self, project: VideoDesignProject) -> VideoDesignProject:
        self._projects[project.project_id] = project
        self._project_path(project.project_id).parent.mkdir(parents=True, exist_ok=True)
        self._project_path(project.project_id).write_text(project.model_dump_json(indent=2), encoding="utf-8")
        return project

    def get(self, project_id: str) -> VideoDesignProject:
        project = self._projects.get(project_id)
        if not project:
            project = self._load(project_id)
        if not project:
            raise VideoDesignError(PROJECT_NOT_FOUND, "Video design project does not exist.")
        return project

    def _load(self, project_id: str) -> VideoDesignProject | None:
        path = self._project_path(project_id)
        if not path.exists():
            return None
        project = VideoDesignProject.model_validate_json(path.read_text(encoding="utf-8"))
        self._projects[project.project_id] = project
        return project

    def _project_path(self, project_id: str) -> Path:
        return settings.storage_dir / project_id / "project.json"
