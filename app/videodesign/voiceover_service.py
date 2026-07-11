from pathlib import Path

from app.videodesign.audio import concatenate_audio_files, measure_audio_duration
from app.videodesign.config import settings
from app.videodesign.errors import (
    AUDIO_COMBINE_FAILED,
    AUDIO_NOT_FOUND,
    SCENE_NOT_READY,
    SCRIPT_REQUIRED,
    VideoDesignError,
)
from app.videodesign.planner import estimate_duration, make_caption_chunks
from app.videodesign.project_state import (
    _delete_project_file,
    _mark_preview_stale,
    _renderable_scenes,
    _reset_smooth_preview,
    _selected_scenes,
)
from app.videodesign.schemas import (
    SceneAudioOffset,
    ScenePlan,
    TTSGenerateRequest,
    TTSMeta,
    TTSSettings,
    VideoDesignProject,
    VoiceoverTrack,
)


class VoiceoverService:
    def __init__(self, store, tts_client):
        self.store = store
        self.tts_client = tts_client

    async def generate_tts(self, project_id: str, request: TTSGenerateRequest) -> dict:
        project = self.store.get(project_id)
        provider = request.provider or project.tts_settings.provider
        voice_id = request.voice_id or project.tts_settings.voice_id
        voice_speed = float(request.voice_speed or project.tts_settings.voice_speed or 1)
        if not request.scene_ids:
            return await self._generate_global_tts(project, provider, voice_id, voice_speed)
        scenes = _selected_scenes(project, request.scene_ids)
        for scene in scenes:
            text = scene.tts_text or scene.voiceover_text
            _delete_project_file(project, scene.tts.audio_path)
            result = await self.tts_client.generate(text, project.project_id, scene.scene_id, provider, voice_id, voice_speed)
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
        project.tts_settings = TTSSettings(language=project.language, provider=provider, voice_id=voice_id, voice_speed=voice_speed)
        _delete_project_file(project, project.voiceover_track.audio_path)
        project.voiceover_track = VoiceoverTrack()
        self.store.put(project)
        return {"success": True, "project": project.model_dump(), "scenes": [scene.model_dump() for scene in scenes]}


    async def _generate_global_tts(self, project: VideoDesignProject, provider: str, voice_id: str, voice_speed: float) -> dict:
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

        result = await self.tts_client.generate(full_text, project.project_id, "global_voiceover", provider, voice_id, voice_speed)
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
        project.tts_settings = TTSSettings(language=project.language, provider=provider, voice_id=voice_id, voice_speed=voice_speed)
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
