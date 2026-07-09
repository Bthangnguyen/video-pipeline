from pathlib import Path

from app.videodesign.config import settings
from app.videodesign.errors import PROJECT_NOT_FOUND, VideoDesignError
from app.videodesign.schemas import VideoDesignProject
from app.shared.redis_store import RedisJsonStore


class VideoDesignStore:
    def __init__(self):
        self._projects: dict[str, VideoDesignProject] = {}
        self.redis = RedisJsonStore("project")

    def put(self, project: VideoDesignProject) -> VideoDesignProject:
        self._projects[project.project_id] = project
        payload = project.model_dump_json(indent=2)
        self.redis.set_text(project.project_id, payload)
        self._project_path(project.project_id).parent.mkdir(parents=True, exist_ok=True)
        self._project_path(project.project_id).write_text(payload, encoding="utf-8")
        return project

    def get(self, project_id: str) -> VideoDesignProject:
        project = self._projects.get(project_id)
        if not project:
            project = self._load_redis(project_id)
        if not project:
            project = self._load(project_id)
        if not project:
            raise VideoDesignError(PROJECT_NOT_FOUND, "Video design project does not exist.")
        return project

    def list(self) -> list[VideoDesignProject]:
        projects = dict(self._projects)
        if settings.storage_dir.exists():
            for path in settings.storage_dir.glob("*/project.json"):
                project_id = path.parent.name
                try:
                    project = self._load(project_id)
                except Exception:
                    continue
                if project:
                    projects[project.project_id] = project
        return list(projects.values())

    def _load(self, project_id: str) -> VideoDesignProject | None:
        path = self._project_path(project_id)
        if not path.exists():
            return None
        project = VideoDesignProject.model_validate_json(path.read_text(encoding="utf-8"))
        self._projects[project.project_id] = project
        return project

    def _load_redis(self, project_id: str) -> VideoDesignProject | None:
        payload = self.redis.get_text(project_id)
        if not payload:
            return None
        try:
            project = VideoDesignProject.model_validate_json(payload)
        except Exception:
            self.redis.delete(project_id)
            return None
        self._projects[project.project_id] = project
        return project

    def _project_path(self, project_id: str) -> Path:
        return settings.storage_dir / project_id / "project.json"
