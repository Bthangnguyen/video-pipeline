import json
import math
import re
import wave
import uuid
from functools import lru_cache
from pathlib import Path

from app.videodesign.audio import measure_audio_duration
from app.videodesign.config import settings
from app.videodesign.errors import PREVIEW_RENDER_FAILED, SCENE_NOT_FOUND, SCENE_NOT_READY, VideoDesignError
from app.videodesign.project_state import _mark_preview_stale
from app.videodesign.schemas import (
    SFXApplyRequest,
    SFXAsset,
    SFXSuggestRequest,
    SFXSuggestion,
    ScenePlan,
    TimelineItem,
    VideoDesignProject,
)


SFX_SAMPLE_RATE = 44100

STATIC_SFX_ROOT = Path(__file__).resolve().parents[2] / "static" / "sfx" / "mixkit"

STATIC_SFX_RECOMMENDED_EVENTS = {
    "pop": ["caption_word", "text_overlay"],
    "click": ["icon", "text_overlay"],
    "whoosh": ["transition", "icon"],
    "impact": ["hook", "transition", "caption_word"],
    "ding": ["icon", "caption_word"],
    "glitch": ["transition", "text_overlay"],
}

STATIC_SFX_DEFAULT_VOLUME = {
    "pop": 0.28,
    "click": 0.22,
    "whoosh": 0.32,
    "impact": 0.34,
    "ding": 0.24,
    "glitch": 0.22,
}

SFX_TRANSITION_PRESETS = {
    "none": {"enabled": False, "category": "none", "volume": 0.0, "duration_seconds": 0.0},
    "clean_cut": {"enabled": False, "category": "none", "volume": 0.0, "duration_seconds": 0.0},
    "fade": {
        "enabled": True,
        "category": "whoosh",
        "asset_ids": ["mixkit_whoosh_air_woosh"],
        "volume": 0.12,
        "duration_seconds": 0.45,
    },
    "dissolve": {
        "enabled": True,
        "category": "whoosh",
        "asset_ids": ["mixkit_whoosh_air_woosh"],
        "volume": 0.1,
        "duration_seconds": 0.45,
    },
    "slide_left": {
        "enabled": True,
        "category": "whoosh",
        "asset_ids": ["mixkit_whoosh_fast_whoosh_transition"],
        "volume": 0.26,
        "duration_seconds": 0.38,
    },
    "slide_right": {
        "enabled": True,
        "category": "whoosh",
        "asset_ids": ["mixkit_whoosh_fast_whoosh_transition"],
        "volume": 0.26,
        "duration_seconds": 0.38,
    },
    "slide_up": {
        "enabled": True,
        "category": "whoosh",
        "asset_ids": ["mixkit_whoosh_fast_rocket_whoosh"],
        "volume": 0.24,
        "duration_seconds": 0.4,
    },
    "push_slide": {
        "enabled": True,
        "category": "whoosh",
        "asset_ids": ["mixkit_whoosh_cinematic_whoosh_fast_transition"],
        "volume": 0.28,
        "duration_seconds": 0.42,
    },
    "whip_pan": {
        "enabled": True,
        "category": "whoosh",
        "asset_ids": ["mixkit_whoosh_cinematic_whoosh_fast_transition"],
        "volume": 0.34,
        "duration_seconds": 0.32,
    },
    "zoom_in": {
        "enabled": True,
        "category": "impact",
        "asset_ids": ["mixkit_impact_quick_zoom_impact"],
        "volume": 0.25,
        "duration_seconds": 0.32,
    },
    "zoom_out": {
        "enabled": True,
        "category": "impact",
        "asset_ids": ["mixkit_impact_quick_zoom_impact"],
        "volume": 0.23,
        "duration_seconds": 0.32,
    },
    "flash_cut": {
        "enabled": True,
        "category": "glitch",
        "asset_ids": ["mixkit_glitch_small_electric_glitch"],
        "volume": 0.22,
        "duration_seconds": 0.24,
    },
    "speed_zoom": {
        "enabled": True,
        "category": "impact",
        "asset_ids": ["mixkit_impact_cinematic_whoosh_deep_impact"],
        "volume": 0.3,
        "duration_seconds": 0.35,
    },
    "fast_swipes": {
        "enabled": True,
        "category": "whoosh",
        "asset_ids": ["mixkit_whoosh_cinematic_whoosh_fast_transition"],
        "volume": 0.3,
        "duration_seconds": 0.35,
    },
}

LEGACY_SFX_DEFS = [
    {
        "asset_id": "sfx_pop_soft",
        "name": "Soft Pop",
        "category": "caption",
        "duration_seconds": 0.24,
        "frequency": 660,
        "default_volume": 0.32,
        "recommended_events": ["caption_word", "text_overlay", "icon"],
    },
    {
        "asset_id": "sfx_click_soft",
        "name": "Soft Click",
        "category": "icon",
        "duration_seconds": 0.18,
        "frequency": 1100,
        "default_volume": 0.24,
        "recommended_events": ["icon", "text_overlay"],
    },
    {
        "asset_id": "sfx_whoosh_short",
        "name": "Short Whoosh",
        "category": "transition",
        "duration_seconds": 0.42,
        "frequency": 320,
        "sweep_to": 880,
        "default_volume": 0.34,
        "recommended_events": ["transition", "icon"],
    },
    {
        "asset_id": "sfx_impact_soft",
        "name": "Soft Impact",
        "category": "hook",
        "duration_seconds": 0.38,
        "frequency": 150,
        "default_volume": 0.38,
        "recommended_events": ["hook", "transition", "caption_word"],
    },
    {
        "asset_id": "sfx_ding",
        "name": "Ding",
        "category": "emphasis",
        "duration_seconds": 0.34,
        "frequency": 880,
        "sweep_to": 1320,
        "default_volume": 0.28,
        "recommended_events": ["icon", "caption_word"],
    },
]


class SFXService:
    def __init__(self, store):
        self.store = store

    def sfx_catalog(self) -> dict:
        assets = _sfx_catalog_assets()
        return {
            "success": True,
            "items": [asset.model_dump() for asset in assets],
            "transition_presets": _sfx_transition_presets_for_ui(),
        }


    def sfx_file_path(self, asset_id: str) -> Path:
        asset = _sfx_asset(asset_id)
        path = Path(asset.local_path)
        if not path.exists():
            raise VideoDesignError(PREVIEW_RENDER_FAILED, "SFX file does not exist.", retryable=True)
        return path


    def suggest_sfx(self, project_id: str, request: SFXSuggestRequest) -> dict:
        project = self.store.get(project_id)
        if not project.timeline:
            raise VideoDesignError(SCENE_NOT_READY, "Timeline has not been created.")
        suggestions = _suggest_sfx_for_project(project, request)
        project.sfx_suggestions = suggestions
        self.store.put(project)
        return {"success": True, "suggestions": [item.model_dump() for item in suggestions]}


    def sfx_suggestions(self, project_id: str) -> dict:
        project = self.store.get(project_id)
        return {"success": True, "suggestions": [item.model_dump() for item in project.sfx_suggestions]}


    def apply_sfx_suggestions(self, project_id: str, request: SFXApplyRequest) -> dict:
        project = self.store.get(project_id)
        if not project.timeline:
            raise VideoDesignError(SCENE_NOT_READY, "Timeline has not been created.")
        selected_ids = set(request.suggestion_ids or [])
        suggestions = [
            item
            for item in project.sfx_suggestions
            if item.status == "proposed" and (not selected_ids or item.suggestion_id in selected_ids)
        ]
        if not suggestions:
            return {"success": True, "applied": [], "timeline": project.timeline.model_dump()}

        existing_event_ids = {
            item.source_ref.get("event_id")
            for item in project.timeline.items
            if item.type == "sfx" and item.source_ref.get("event_id")
        }
        applied = []
        for suggestion in suggestions:
            if suggestion.suggestion_id in request.volume_overrides:
                suggestion.volume = _clamp_sfx_volume(request.volume_overrides[suggestion.suggestion_id])
            if suggestion.event_id in existing_event_ids:
                suggestion.status = "applied"
                continue
            asset = _sfx_asset(suggestion.asset_id)
            start = max(0.0, float(suggestion.time_seconds))
            sfx_duration = max(
                0.05,
                min(float(asset.duration_seconds or 0.25), float(suggestion.duration_hint_seconds or asset.duration_seconds or 0.25)),
            )
            end = min(
                max(start + 0.05, start + sfx_duration),
                max(start + 0.05, float(project.timeline.duration_seconds or start + 0.25)),
            )
            item = TimelineItem(
                item_id=f"itm_{uuid.uuid4().hex}",
                layer_id="sfx",
                scene_id=suggestion.scene_id,
                type="sfx",
                start_seconds=round(start, 3),
                end_seconds=round(end, 3),
                source_ref={
                    "asset_id": asset.asset_id,
                    "audio_url": asset.audio_url,
                    "event_id": suggestion.event_id,
                    "event_type": suggestion.event_type,
                    "label": suggestion.label,
                },
                style={"volume": suggestion.volume, "enabled": True},
            )
            project.timeline.items.append(item)
            if "sfx" not in project.timeline.layers:
                project.timeline.layers.append("sfx")
            suggestion.status = "applied"
            existing_event_ids.add(suggestion.event_id)
            applied.append(item)

        _mark_preview_stale(project)
        self.store.put(project)
        return {
            "success": True,
            "applied": [item.model_dump() for item in applied],
            "suggestions": [item.model_dump() for item in project.sfx_suggestions],
            "timeline": project.timeline.model_dump(),
        }


def _sfx_catalog_dir() -> Path:
    path = settings.storage_dir / "_sfx_catalog"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _sfx_catalog_assets() -> list[SFXAsset]:
    return list(_static_sfx_catalog_assets())


def _sfx_transition_presets_for_ui() -> list[dict]:
    items = []
    for transition_id, preset in SFX_TRANSITION_PRESETS.items():
        asset_id = _sfx_asset_for_transition(transition_id)
        asset = _sfx_asset(asset_id) if asset_id else None
        items.append(
            {
                "transition_id": transition_id,
                "enabled": bool(preset.get("enabled")),
                "category": preset.get("category", "none"),
                "asset_id": asset.asset_id if asset else "",
                "asset_name": asset.name if asset else "No SFX",
                "volume": float(preset.get("volume", 0)),
                "duration_seconds": float(preset.get("duration_seconds", 0)),
            }
        )
    return items


def _sfx_asset(asset_id: str) -> SFXAsset:
    static_asset = next((asset for asset in _static_sfx_catalog_assets() if asset.asset_id == asset_id), None)
    if static_asset:
        return static_asset
    return _generated_sfx_asset(asset_id)


def _static_sfx_catalog_assets() -> tuple[SFXAsset, ...]:
    catalog_path = STATIC_SFX_ROOT / "catalog.json"
    if not catalog_path.exists():
        return tuple()
    try:
        items = json.loads(catalog_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return tuple()
    assets: list[SFXAsset] = []
    for item in items:
        filename = str(item.get("filename") or "").strip()
        asset_id = str(item.get("asset_id") or "").strip()
        if not filename or not asset_id:
            continue
        local_path = STATIC_SFX_ROOT / filename
        if not local_path.exists():
            continue
        category = str(item.get("category") or "sfx").strip()
        duration = _safe_audio_duration(local_path)
        assets.append(
            SFXAsset(
                asset_id=asset_id,
                name=str(item.get("name") or asset_id),
                category=category,
                audio_url=str(item.get("audio_url") or f"/static/sfx/mixkit/{filename}"),
                local_path=str(local_path),
                duration_seconds=duration,
                default_volume=float(STATIC_SFX_DEFAULT_VOLUME.get(category, 0.28)),
                recommended_events=list(STATIC_SFX_RECOMMENDED_EVENTS.get(category, ["transition", "caption_word"])),
            )
        )
    return tuple(assets)


def _safe_audio_duration(path: Path) -> float:
    try:
        return max(0.05, round(measure_audio_duration(path), 3))
    except Exception:
        return 0.35


def _generated_sfx_asset(asset_id: str) -> SFXAsset:
    definition = next((item for item in LEGACY_SFX_DEFS if item["asset_id"] == asset_id), None)
    if not definition:
        raise VideoDesignError(SCENE_NOT_FOUND, "SFX asset does not exist.")
    local_path = _ensure_sfx_file(definition)
    return SFXAsset(
        asset_id=definition["asset_id"],
        name=definition["name"],
        category=definition["category"],
        audio_url=f"/api/videodesign/sfx/{definition['asset_id']}/file",
        local_path=str(local_path),
        duration_seconds=float(definition["duration_seconds"]),
        default_volume=float(definition["default_volume"]),
        recommended_events=list(definition["recommended_events"]),
    )


def _ensure_sfx_file(definition: dict) -> Path:
    path = _sfx_catalog_dir() / f"{definition['asset_id']}.wav"
    if path.exists():
        return path
    _write_tone_wav(
        path,
        duration_seconds=float(definition["duration_seconds"]),
        frequency=float(definition["frequency"]),
        sweep_to=float(definition.get("sweep_to") or definition["frequency"]),
        volume=float(definition["default_volume"]),
    )
    return path


def _write_tone_wav(path: Path, duration_seconds: float, frequency: float, sweep_to: float, volume: float) -> None:
    frame_count = max(1, int(SFX_SAMPLE_RATE * duration_seconds))
    max_amp = int(32767 * max(0.05, min(volume, 0.75)))
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SFX_SAMPLE_RATE)
        frames = bytearray()
        for index in range(frame_count):
            position = index / max(1, frame_count - 1)
            freq = frequency + (sweep_to - frequency) * position
            envelope = math.sin(math.pi * position)
            if position < 0.08:
                envelope *= position / 0.08
            sample = int(math.sin(2 * math.pi * freq * (index / SFX_SAMPLE_RATE)) * max_amp * envelope)
            frames.extend(sample.to_bytes(2, "little", signed=True))
        wav.writeframes(bytes(frames))


def _suggest_sfx_for_project(project: VideoDesignProject, request: SFXSuggestRequest) -> list[SFXSuggestion]:
    media_items = sorted(
        [item for item in (project.timeline.items if project.timeline else []) if item.type == "media"],
        key=lambda item: item.start_seconds,
    )
    suggestions: list[SFXSuggestion] = []
    if request.include_hook and media_items:
        asset_id = _sfx_asset_for_category("impact")
        if asset_id:
            suggestions.append(
                _make_sfx_suggestion(
                    project,
                    event_id="evt_hook_start",
                    scene_id=media_items[0].scene_id,
                    event_type="hook",
                    time_seconds=0,
                    asset_id=asset_id,
                    label="Opening hook impact",
                    reason="Adds a subtle accent at the start of the video.",
                    priority=0.95,
                )
            )
    if request.include_transitions:
        for transition in sorted([item for item in project.timeline.items if item.type == "transition"], key=lambda item: item.start_seconds):
            transition_id = str(transition.style.get("transition_id") or transition.source_ref.get("transition_id") or "fade")
            preset = _sfx_transition_preset(transition_id)
            if not preset.get("enabled"):
                continue
            transition_label = transition_id.replace("_", " ")
            asset_id = _sfx_asset_for_transition(str(transition_id))
            if not asset_id:
                continue
            duration_hint = min(
                float(preset.get("duration_seconds", 0.35) or 0.35),
                max(0.08, float(transition.end_seconds - transition.start_seconds) + 0.1),
            )
            suggestions.append(
                _make_sfx_suggestion(
                    project,
                    event_id=f"evt_transition_{transition.item_id}",
                    scene_id=transition.scene_id,
                    event_type="transition",
                    time_seconds=transition.start_seconds,
                    asset_id=asset_id,
                    label=f"{transition_label} transition",
                    reason=f"Transition uses {transition_label}, so a short accent can make the cut feel intentional.",
                    priority=0.9,
                    volume=float(preset.get("volume", 0.25)),
                    duration_hint_seconds=duration_hint,
                )
            )
    if request.include_icons:
        for icon in sorted([item for item in project.timeline.items if item.type == "icon"], key=lambda item: item.start_seconds):
            icon_id = str(icon.source_ref.get("icon_id") or "icon")
            asset_id = _sfx_asset_for_icon(icon_id)
            if not asset_id:
                continue
            suggestions.append(
                _make_sfx_suggestion(
                    project,
                    event_id=f"evt_icon_{icon.item_id}",
                    scene_id=icon.scene_id,
                    event_type="icon",
                    time_seconds=icon.start_seconds,
                    asset_id=asset_id,
                    label=f"{icon_id.replace('_', ' ')} icon",
                    reason="Icon appears on screen and can use a small emphasis sound.",
                    priority=0.72,
                )
            )
    if request.include_text:
        for text_item in sorted([item for item in project.timeline.items if item.type == "text"], key=lambda item: item.start_seconds):
            text = str(text_item.source_ref.get("text") or "").strip()
            if not text:
                continue
            asset_id = _sfx_asset_for_category("pop")
            if not asset_id:
                continue
            suggestions.append(
                _make_sfx_suggestion(
                    project,
                    event_id=f"evt_text_{text_item.item_id}",
                    scene_id=text_item.scene_id,
                    event_type="text_overlay",
                    time_seconds=text_item.start_seconds,
                    asset_id=asset_id,
                    label="Text pop",
                    reason="Text overlay starts here.",
                    priority=0.62,
                )
            )
    if request.include_caption_words:
        for media in media_items:
            scene = next((item for item in project.scenes if item.scene_id == media.scene_id), None)
            if not scene:
                continue
            suggestions.extend(_caption_word_sfx_suggestions(project, scene, media))

    return _dedupe_sfx_suggestions(suggestions, request.max_suggestions)


def _make_sfx_suggestion(
    project: VideoDesignProject,
    event_id: str,
    scene_id: str,
    event_type: str,
    time_seconds: float,
    asset_id: str,
    label: str,
    reason: str,
    priority: float,
    volume: float | None = None,
    duration_hint_seconds: float | None = None,
) -> SFXSuggestion:
    asset = _sfx_asset(asset_id)
    return SFXSuggestion(
        suggestion_id=f"sgx_{uuid.uuid4().hex}",
        event_id=event_id,
        project_id=project.project_id,
        scene_id=scene_id,
        event_type=event_type,
        time_seconds=round(max(0.0, float(time_seconds)), 3),
        duration_hint_seconds=round(max(0.05, float(duration_hint_seconds or asset.duration_seconds)), 3),
        label=label,
        reason=reason,
        asset_id=asset.asset_id,
        volume=_clamp_sfx_volume(volume if volume is not None else asset.default_volume),
    )


def _caption_word_sfx_suggestions(project: VideoDesignProject, scene: ScenePlan, media: TimelineItem) -> list[SFXSuggestion]:
    text = scene.caption_text or scene.tts_text or scene.voiceover_text
    words = re.findall(r"[A-Za-z0-9']+", text or "")
    if not words:
        return []
    duration = max(0.25, float(media.end_seconds - media.start_seconds))
    indexes = _important_caption_word_indexes(words)
    suggestions = []
    for index in indexes[:2]:
        word = words[index]
        local = duration * (index / max(1, len(words)))
        asset_id = _sfx_asset_for_category("ding" if any(char.isdigit() for char in word) else "pop")
        if not asset_id:
            continue
        suggestions.append(
            _make_sfx_suggestion(
                project,
                event_id=f"evt_caption_{scene.scene_id}_{index}",
                scene_id=scene.scene_id,
                event_type="caption_word",
                time_seconds=float(media.start_seconds) + local,
                asset_id=asset_id,
                label=f"Caption accent: {word}",
                reason="Important caption word can use a small pop, not every word.",
                priority=0.5 if index else 0.68,
            )
        )
    return suggestions


def _important_caption_word_indexes(words: list[str]) -> list[int]:
    indexes = [0]
    for index, word in enumerate(words):
        clean = word.strip("'").lower()
        if index == 0:
            continue
        if len(clean) <= 2:
            continue
        if any(char.isdigit() for char in clean) or word.isupper() or clean in {"now", "stop", "secret", "never", "always", "money", "truth", "watch"}:
            indexes.append(index)
        if len(indexes) >= 3:
            break
    return sorted(set(indexes))


def _dedupe_sfx_suggestions(suggestions: list[SFXSuggestion], limit: int) -> list[SFXSuggestion]:
    priority = {
        "hook": 5,
        "transition": 4,
        "icon": 3,
        "text_overlay": 2,
        "caption_word": 1,
    }
    sorted_items = sorted(
        suggestions,
        key=lambda item: (-priority.get(item.event_type, 0), item.time_seconds),
    )
    accepted: list[SFXSuggestion] = []
    for suggestion in sorted_items:
        if any(abs(suggestion.time_seconds - existing.time_seconds) < 0.45 for existing in accepted):
            continue
        accepted.append(suggestion)
        if len(accepted) >= limit:
            break
    return sorted(accepted, key=lambda item: item.time_seconds)


def _sfx_asset_for_transition(transition_id: str) -> str:
    preset = _sfx_transition_preset(transition_id)
    if not preset.get("enabled"):
        return ""
    return _sfx_asset_from_preset(preset)


def _sfx_transition_preset(transition_id: str) -> dict:
    return SFX_TRANSITION_PRESETS.get(str(transition_id or "fade"), SFX_TRANSITION_PRESETS["fade"])


def _sfx_asset_from_preset(preset: dict) -> str:
    for asset_id in preset.get("asset_ids", []):
        if _static_sfx_asset_exists(str(asset_id)):
            return str(asset_id)
    category = str(preset.get("category") or "")
    if category and category != "none":
        return _sfx_asset_for_category(category)
    return ""


def _static_sfx_asset_exists(asset_id: str) -> bool:
    return any(item.asset_id == asset_id for item in _static_sfx_catalog_assets())


def _sfx_asset_for_icon(icon_id: str) -> str:
    if icon_id in {"check", "starburst"}:
        return _sfx_asset_for_category("ding")
    if icon_id in {"arrow_right", "pointer"}:
        return _sfx_asset_for_category("whoosh")
    return _sfx_asset_for_category("click")


def _sfx_asset_for_category(category: str) -> str:
    asset = next((item for item in _static_sfx_catalog_assets() if item.category == category), None)
    return asset.asset_id if asset else ""


def _clamp_sfx_volume(value: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = 0.35
    return round(max(0.0, min(1.0, number)), 3)
