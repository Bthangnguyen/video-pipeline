import re
import uuid
from pathlib import Path

from app.videodesign.audio import measure_audio_duration
from app.videodesign.config import settings
from app.videodesign.errors import (
    AUDIO_NOT_FOUND,
    INVALID_PROJECT_INPUT,
    SCENE_NOT_FOUND,
    SCENE_NOT_READY,
    VideoDesignError,
)
from app.videodesign.materials.candidates import _asset
from app.videodesign.materials.proxy import _ensure_preview_proxy
from app.videodesign.planner import estimate_duration
from app.videodesign.project_state import (
    _delete_project_file,
    _mark_preview_stale,
    _renderable_scenes,
    _reset_smooth_preview,
    _scene,
)
from app.videodesign.schemas import (
    MaterialAsset,
    SceneClip,
    SceneClipPatch,
    ScenePlan,
    TimelineDraft,
    TimelineItem,
    TimelineItemCreateRequest,
    TimelineItemPatch,
    TransitionRequest,
    VideoDesignProject,
)
from app.videodesign.studio.constants import TIMELINE_MIN_ITEM_DURATION


class StudioService:
    def __init__(self, store):
        self.store = store
        self.ensure_preview_proxy = _ensure_preview_proxy

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
            await self.ensure_preview_proxy(asset, project.aspect_ratio)
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
            _apply_video_defaults_to_clip(scene.clip, project.design_preset)
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
            layers=["media_base", "overlay_default", "caption_default", "text_overlay", "icon", "voiceover_audio", "background_audio", "transition_out", "sfx"],
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


    def upload_background_music(self, project_id: str, filename: str, content: bytes, content_type: str = "") -> dict:
        project = self.store.get(project_id)
        if not project.timeline:
            raise VideoDesignError(SCENE_NOT_READY, "Timeline has not been created.")
        if not content:
            raise VideoDesignError(INVALID_PROJECT_INPUT, "Music file is empty.")
        suffix = Path(filename or "").suffix.lower()
        allowed_suffixes = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"}
        if suffix not in allowed_suffixes and not str(content_type or "").startswith("audio/"):
            raise VideoDesignError(INVALID_PROJECT_INPUT, "Upload an audio file for background music.")
        if suffix not in allowed_suffixes:
            suffix = ".mp3"
        music_dir = settings.storage_dir / project.project_id / "music"
        music_dir.mkdir(parents=True, exist_ok=True)
        item_id = f"itm_{uuid.uuid4().hex}"
        safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "-", Path(filename or "background-music").stem).strip("-") or "background-music"
        output_path = music_dir / f"{item_id}-{safe_name}{suffix}"
        output_path.write_bytes(content)
        try:
            duration_seconds = measure_audio_duration(output_path)
        except Exception as exc:
            _delete_project_file(project, str(output_path))
            raise VideoDesignError(INVALID_PROJECT_INPUT, f"Could not read uploaded music: {exc}") from exc

        for old_item in [item for item in project.timeline.items if item.type == "music"]:
            _delete_project_file(project, str(old_item.source_ref.get("local_path") or ""))
        project.timeline.items = [item for item in project.timeline.items if item.type != "music"]
        scene_id = project.timeline.scenes[0] if project.timeline.scenes else project.scenes[0].scene_id
        duration = max(0.25, float(project.timeline.duration_seconds or duration_seconds or 0.25))
        item = TimelineItem(
            item_id=item_id,
            layer_id="background_audio",
            scene_id=scene_id,
            type="music",
            start_seconds=0,
            end_seconds=round(duration, 3),
            source_ref={
                "name": Path(filename or "Background music").name,
                "local_path": str(output_path),
                "audio_url": f"/api/videodesign/projects/{project.project_id}/music/{item_id}/file",
                "duration_seconds": round(float(duration_seconds or 0), 3),
                "trim_start_seconds": 0,
                "trim_end_seconds": round(float(duration_seconds or 0), 3),
            },
            style={
                "enabled": True,
                "volume": 0.16,
                "ducking": True,
                "ducking_volume": 0.08,
                "fade_in_seconds": 1.0,
                "fade_out_seconds": 1.0,
                "loop": True,
            },
        )
        if "background_audio" not in project.timeline.layers:
            project.timeline.layers.append("background_audio")
        project.timeline.items.append(item)
        _mark_preview_stale(project)
        self.store.put(project)
        return {"success": True, "item": item.model_dump(), "timeline": project.timeline.model_dump()}


    def background_music_file_path(self, project_id: str, item_id: str) -> Path:
        project = self.store.get(project_id)
        if not project.timeline:
            raise VideoDesignError(SCENE_NOT_READY, "Timeline has not been created.")
        item = next((entry for entry in project.timeline.items if entry.item_id == item_id and entry.type == "music"), None)
        if not item:
            raise VideoDesignError(SCENE_NOT_FOUND, "Background music item does not exist.")
        path = Path(str(item.source_ref.get("local_path") or ""))
        if not path.exists():
            raise VideoDesignError(AUDIO_NOT_FOUND, "Background music file does not exist.", retryable=True)
        return path


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
        deleted_item = next((item for item in project.timeline.items if item.item_id == item_id), None)
        project.timeline.items = [item for item in project.timeline.items if item.item_id != item_id]
        if len(project.timeline.items) == before:
            raise VideoDesignError(SCENE_NOT_FOUND, "Timeline item does not exist.")
        if deleted_item and deleted_item.type == "music":
            _delete_project_file(project, str(deleted_item.source_ref.get("local_path") or ""))
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


def _apply_video_defaults_to_clip(clip: SceneClip, preset: dict | None) -> None:
    defaults = (preset or {}).get("video_defaults") or {}
    transform = dict(clip.transform or {})
    effects = dict(clip.effects or {})
    if defaults.get("flip_horizontal") and not transform.get("flip_horizontal"):
        transform["flip_horizontal"] = True
    for key, default_value in {
        "brightness": defaults.get("brightness"),
        "contrast": defaults.get("contrast"),
        "saturation": defaults.get("saturation"),
    }.items():
        if default_value in (None, ""):
            continue
        current = float(effects.get(key, 1) or 1)
        if abs(current - 1) < 0.001:
            effects[key] = float(default_value)
    clip.transform = transform
    clip.effects = effects


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
        "music": "background_audio",
        "overlay": "overlay_default",
        "sfx": "sfx",
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
    if item_type == "sfx":
        return min(bounds[1], start + 0.35)
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
    transition_pack_id = _transition_id_from_preset(extras.get("transition_pack_id") or "fade", scene.order)
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


def _transition_id_from_preset(transition_pack_id: str, scene_order: int) -> str:
    if transition_pack_id == "mix":
        choices = ["fade", "slide_left", "zoom_in", "dissolve"]
        return choices[(max(1, int(scene_order)) - 1) % len(choices)]
    return transition_pack_id
