import asyncio
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.videodesign.config import settings
from app.videodesign.errors import PREVIEW_RENDER_FAILED, SCENE_NOT_READY, VideoDesignError
from app.videodesign.materials.candidates import _asset
from app.videodesign.materials.proxy import _ensure_preview_proxy, _proxy_resolution
from app.videodesign.project_state import _project_title
from app.videodesign.schemas import SFXAsset, SmoothPreview, TimelineItem, VideoDesignProject
from app.videodesign.studio.constants import TIMELINE_MIN_ITEM_DURATION
from app.videodesign.studio.sfx import _sfx_asset


class RenderService:
    def __init__(self, store):
        self.store = store
        self.render_preview_file = _render_smooth_preview_file

    def preview_status(self, project_id: str) -> dict:
        project = self.store.get(project_id)
        return {"success": True, "preview": project.smooth_preview.model_dump()}


    async def render_smooth_preview(self, project_id: str) -> dict:
        project = self.store.get(project_id)
        if not project.timeline:
            raise VideoDesignError(SCENE_NOT_READY, "Timeline has not been created.")
        project.smooth_preview.status = "rendering"
        project.smooth_preview.error = {}
        self.store.put(project)
        try:
            path = await self.render_preview_file(project)
        except VideoDesignError as error:
            project.smooth_preview.status = "failed"
            project.smooth_preview.error = error.to_payload()
            self.store.put(project)
            raise
        except Exception as exc:
            error = VideoDesignError(PREVIEW_RENDER_FAILED, f"Could not render smooth preview: {exc}", retryable=True)
            project.smooth_preview.status = "failed"
            project.smooth_preview.error = error.to_payload()
            self.store.put(project)
            raise error from exc

        updated_at = datetime.now(timezone.utc).isoformat()
        project.smooth_preview = SmoothPreview(
            status="ready",
            preview_url=_smooth_preview_url(project.project_id, updated_at),
            preview_path=str(path),
            timeline_id=project.timeline.timeline_id,
            duration_seconds=project.timeline.duration_seconds,
            updated_at=updated_at,
        )
        self.store.put(project)
        return {"success": True, "preview": project.smooth_preview.model_dump()}


    async def render_export(self, project_id: str) -> dict:
        result = await self.render_smooth_preview(project_id)
        return {
            "success": True,
            "preview": result["preview"],
            "export_url": _export_url(project_id),
        }


    def export_file_path(self, project_id: str) -> Path:
        project = self.store.get(project_id)
        if project.smooth_preview.status != "ready" or not project.smooth_preview.preview_path:
            raise VideoDesignError(PREVIEW_RENDER_FAILED, "Render the export before downloading the MP4.", retryable=True)
        path = Path(project.smooth_preview.preview_path)
        if not path.exists():
            raise VideoDesignError(PREVIEW_RENDER_FAILED, "Rendered export file does not exist.", retryable=True)
        return path


    def export_filename(self, project_id: str) -> str:
        project = self.store.get(project_id)
        title = _project_title(project)
        return f"{_safe_filename(title)}.mp4"


    def smooth_preview_file_path(self, project_id: str) -> Path:
        project = self.store.get(project_id)
        if project.smooth_preview.status not in {"ready", "stale"} or not project.smooth_preview.preview_path:
            raise VideoDesignError(PREVIEW_RENDER_FAILED, "Smooth preview has not been rendered yet.", retryable=True)
        path = Path(project.smooth_preview.preview_path)
        if not path.exists():
            raise VideoDesignError(PREVIEW_RENDER_FAILED, "Smooth preview file does not exist.", retryable=True)
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



def _smooth_preview_url(project_id: str, updated_at: str) -> str:
    cache_key = re.sub(r"[^0-9A-Za-z]", "", updated_at) or uuid.uuid4().hex
    return f"/api/videodesign/projects/{project_id}/preview/file?v={cache_key}"


def _export_url(project_id: str) -> str:
    return f"/api/videodesign/projects/{project_id}/export/file"


def _safe_filename(value: str) -> str:
    filename = re.sub(r"[^0-9A-Za-z._-]+", "-", value.strip()).strip(".-")
    return filename[:80] or "videodesign-export"


async def _render_smooth_preview_file(project: VideoDesignProject) -> Path:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise VideoDesignError(PREVIEW_RENDER_FAILED, "FFmpeg is not available for smooth preview rendering.", retryable=True)
    if not project.timeline:
        raise VideoDesignError(SCENE_NOT_READY, "Timeline has not been created.")

    media_items = sorted(
        [item for item in project.timeline.items if item.type == "media"],
        key=lambda item: item.start_seconds,
    )
    if not media_items:
        raise VideoDesignError(SCENE_NOT_READY, "Timeline has no media items to render.")

    for item in media_items:
        asset = _asset(project, str(item.source_ref.get("asset_id") or ""))
        await _ensure_preview_proxy(asset, project.aspect_ratio)

    output_dir = settings.storage_dir / project.project_id / "previews"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "timeline_preview.mp4"
    temp_path = output_dir / f"timeline_preview.{uuid.uuid4().hex}.tmp.mp4"

    transition_by_scene: dict[str, TimelineItem] = {}
    for item in project.timeline.items:
        if item.type != "transition":
            continue
        transition_id = item.style.get("transition_id") or item.source_ref.get("transition_id")
        if transition_id and transition_id != "none":
            transition_by_scene[item.scene_id] = item
    command = [ffmpeg, "-y"]
    width, height = _proxy_resolution(project.aspect_ratio)
    incoming_transition = 0.0
    input_durations: list[float] = []
    input_trim_starts: list[float] = []
    for index, item in enumerate(media_items):
        asset = _asset(project, str(item.source_ref.get("asset_id") or ""))
        input_path = Path(asset.proxy_path or asset.local_path)
        has_video_stream = await _has_video_stream(input_path)
        if not input_path.exists():
            raise VideoDesignError(PREVIEW_RENDER_FAILED, f"Media file does not exist for scene {item.scene_id}.", retryable=True)
        scene_duration = max(TIMELINE_MIN_ITEM_DURATION, float(item.end_seconds - item.start_seconds))
        input_duration = scene_duration + (incoming_transition if index > 0 else 0)
        input_durations.append(input_duration)
        if has_video_stream:
            input_trim_starts.append(max(0.0, float(item.source_ref.get("trim_start_seconds") or 0)))
            command.extend(["-stream_loop", "-1", "-i", str(input_path)])
        else:
            input_trim_starts.append(0.0)
            command.extend(
                [
                    "-f",
                    "lavfi",
                    "-t",
                    _ffmpeg_seconds(input_duration),
                    "-i",
                    f"color=c=black:s={width}x{height}:r=30",
                ]
            )
        transition = transition_by_scene.get(item.scene_id)
        incoming_transition = _transition_duration_for_render(transition, scene_duration) if transition else 0.0

    audio_input_index: int | None = None
    if project.voiceover_track.audio_path and Path(project.voiceover_track.audio_path).exists():
        audio_input_index = len(media_items)
        command.extend(["-i", str(Path(project.voiceover_track.audio_path))])
    music_inputs: list[tuple[TimelineItem, int, Path]] = []
    for item in sorted([entry for entry in project.timeline.items if entry.type == "music"], key=lambda entry: entry.start_seconds):
        if item.style.get("enabled") is False:
            continue
        path = Path(str(item.source_ref.get("local_path") or ""))
        if not path.exists():
            continue
        input_index = len(media_items) + (1 if audio_input_index is not None else 0) + len(music_inputs)
        if item.style.get("loop", True):
            command.extend(["-stream_loop", "-1"])
        command.extend(["-i", str(path)])
        music_inputs.append((item, input_index, path))
    sfx_inputs: list[tuple[TimelineItem, int, SFXAsset]] = []
    for item in sorted([entry for entry in project.timeline.items if entry.type == "sfx"], key=lambda entry: entry.start_seconds):
        if item.style.get("enabled") is False:
            continue
        asset_id = str(item.source_ref.get("asset_id") or "")
        if not asset_id:
            continue
        try:
            asset = _sfx_asset(asset_id)
        except VideoDesignError:
            continue
        path = Path(asset.local_path)
        if not path.exists():
            continue
        input_index = len(media_items) + (1 if audio_input_index is not None else 0) + len(music_inputs) + len(sfx_inputs)
        command.extend(["-i", str(path)])
        sfx_inputs.append((item, input_index, asset))

    filter_parts: list[str] = []
    for index, item in enumerate(media_items):
        filter_parts.append(_media_render_filter(index, item, input_durations[index], width, height, input_trim_starts[index]))

    chain = "v0"
    for index, item in enumerate(media_items[:-1]):
        transition = transition_by_scene.get(item.scene_id)
        next_label = f"v{index + 1}"
        output_label = f"x{index}"
        if transition:
            scene_duration = max(TIMELINE_MIN_ITEM_DURATION, float(item.end_seconds - item.start_seconds))
            duration = _transition_duration_for_render(transition, scene_duration)
            offset = max(0.0, float(item.end_seconds) - duration)
            transition_id = _ffmpeg_transition_id(transition)
            filter_parts.append(
                f"[{chain}][{next_label}]xfade=transition={transition_id}:duration={_ffmpeg_seconds(duration)}:"
                f"offset={_ffmpeg_seconds(offset)},format=yuv420p[{output_label}]"
            )
        else:
            filter_parts.append(f"[{chain}][{next_label}]concat=n=2:v=1:a=0,setpts=PTS-STARTPTS,format=yuv420p[{output_label}]")
        chain = output_label

    duration = max(TIMELINE_MIN_ITEM_DURATION, float(project.timeline.duration_seconds or media_items[-1].end_seconds))
    audio_label = _append_audio_mix_filters(filter_parts, audio_input_index, music_inputs, sfx_inputs, duration)
    command.extend(["-filter_complex", ";".join(filter_parts), "-map", f"[{chain}]"])
    if audio_label:
        command.extend(["-map", f"[{audio_label}]", "-c:a", "aac", "-b:a", "160k"])
    else:
        command.append("-an")
    command.extend(
        [
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "23",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            "-t",
            _ffmpeg_seconds(duration),
            str(temp_path),
        ]
    )

    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    timeout = max(180.0, duration * 10)
    try:
        _, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except asyncio.TimeoutError as exc:
        process.kill()
        await process.communicate()
        if temp_path.exists():
            temp_path.unlink()
        raise VideoDesignError(PREVIEW_RENDER_FAILED, "Smooth preview render timed out.", retryable=True) from exc

    if process.returncode != 0 or not temp_path.exists():
        if temp_path.exists():
            temp_path.unlink()
        message = (stderr or b"").decode(errors="ignore").strip()[-1400:]
        raise VideoDesignError(PREVIEW_RENDER_FAILED, f"FFmpeg smooth preview render failed: {message}", retryable=True)

    if output_path.exists():
        output_path.unlink()
    temp_path.replace(output_path)
    return output_path


async def _has_video_stream(path: Path) -> bool:
    if not path.exists():
        return False
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return True
    process = await asyncio.create_subprocess_exec(
        ffprobe,
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=codec_type",
        "-of",
        "csv=p=0",
        str(path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout=20)
    except asyncio.TimeoutError:
        process.kill()
        await process.communicate()
        return False
    return process.returncode == 0 and "video" in stdout.decode(errors="ignore").lower()


def _media_render_filter(index: int, item: TimelineItem, duration: float, width: int, height: int, trim_start: float | None = None) -> str:
    trim_start = max(0.0, float(item.source_ref.get("trim_start_seconds") if trim_start is None else trim_start) or 0)
    filters = [
        f"trim=start={_ffmpeg_seconds(trim_start)}:duration={_ffmpeg_seconds(duration)}",
        "setpts=PTS-STARTPTS",
    ]
    if item.transform.get("flip_horizontal"):
        filters.append("hflip")
    filters.extend(
        [
            f"scale={width}:{height}:force_original_aspect_ratio=increase",
            f"crop={width}:{height}",
            "fps=30",
        ]
    )
    effects = item.source_ref.get("effects") or {}
    eq = _eq_filter(effects)
    if eq:
        filters.append(eq)
    filters.append("format=yuv420p")
    return f"[{index}:v]{','.join(filters)}[v{index}]"


def _music_trim_bounds(item: TimelineItem) -> tuple[float, float]:
    source_duration = max(0.05, float(item.source_ref.get("duration_seconds") or 0.05))
    trim_start = max(0.0, min(float(item.source_ref.get("trim_start_seconds") or 0), source_duration - 0.05))
    raw_end = item.source_ref.get("trim_end_seconds")
    trim_end = source_duration if raw_end in (None, "") else float(raw_end or source_duration)
    trim_end = max(trim_start + 0.05, min(trim_end, source_duration))
    return round(trim_start, 3), round(trim_end, 3)


def _append_audio_mix_filters(
    filter_parts: list[str],
    voiceover_input_index: int | None,
    music_inputs: list[tuple[TimelineItem, int, Path]],
    sfx_inputs: list[tuple[TimelineItem, int, SFXAsset]],
    duration: float,
) -> str:
    audio_labels: list[str] = []
    if voiceover_input_index is not None:
        filter_parts.append(
            f"[{voiceover_input_index}:a]atrim=0:{_ffmpeg_seconds(duration)},"
            f"asetpts=PTS-STARTPTS,volume=1.0[a_voice]"
        )
        audio_labels.append("a_voice")
    for index, (item, input_index, _path) in enumerate(music_inputs):
        start = max(0.0, float(item.start_seconds or 0))
        end = max(start + 0.05, min(float(item.end_seconds or duration), duration))
        item_duration = max(0.05, end - start)
        start_ms = max(0, int(start * 1000))
        trim_start, trim_end = _music_trim_bounds(item)
        trim_duration = max(0.05, trim_end - trim_start)
        base_volume = float(item.style.get("volume", 0.16) or 0.16)
        ducking_volume = float(item.style.get("ducking_volume", 0.08) or 0.08)
        volume = ducking_volume if voiceover_input_index is not None and item.style.get("ducking", True) else base_volume
        volume = max(0.0, min(1.0, volume))
        fade_in = max(0.0, min(float(item.style.get("fade_in_seconds", 0) or 0), item_duration / 2))
        fade_out = max(0.0, min(float(item.style.get("fade_out_seconds", 0) or 0), item_duration / 2))
        filters = [
            "aresample=44100",
            f"atrim=start={_ffmpeg_seconds(trim_start)}:end={_ffmpeg_seconds(trim_end)}",
            "asetpts=PTS-STARTPTS",
        ]
        if item.style.get("loop", True):
            filters.append(f"aloop=loop=-1:size={max(1, int(trim_duration * 44100))}")
        filters.extend(
            [
                f"atrim=0:{_ffmpeg_seconds(item_duration)}",
                "asetpts=PTS-STARTPTS",
                f"volume={volume:.3f}",
            ]
        )
        if fade_in > 0:
            filters.append(f"afade=t=in:st=0:d={_ffmpeg_seconds(fade_in)}")
        if fade_out > 0:
            filters.append(f"afade=t=out:st={_ffmpeg_seconds(max(0.0, item_duration - fade_out))}:d={_ffmpeg_seconds(fade_out)}")
        filters.append(f"adelay={start_ms}:all=1")
        label = f"a_music_{index}"
        filter_parts.append(f"[{input_index}:a]{','.join(filters)}[{label}]")
        audio_labels.append(label)
    for index, (item, input_index, asset) in enumerate(sfx_inputs):
        start_ms = max(0, int(float(item.start_seconds or 0) * 1000))
        item_duration = max(0.05, min(float(asset.duration_seconds or 0.25), float(item.end_seconds - item.start_seconds or asset.duration_seconds or 0.25)))
        volume = max(0.0, min(2.0, float(item.style.get("volume", asset.default_volume) or asset.default_volume)))
        label = f"a_sfx_{index}"
        filter_parts.append(
            f"[{input_index}:a]atrim=0:{_ffmpeg_seconds(item_duration)},asetpts=PTS-STARTPTS,"
            f"volume={volume:.3f},adelay={start_ms}:all=1[{label}]"
        )
        audio_labels.append(label)
    if not audio_labels:
        return ""
    if len(audio_labels) == 1:
        label = "aout"
        filter_parts.append(f"[{audio_labels[0]}]apad,atrim=0:{_ffmpeg_seconds(duration)}[{label}]")
        return label
    input_labels = "".join(f"[{label}]" for label in audio_labels)
    filter_parts.append(
        f"{input_labels}amix=inputs={len(audio_labels)}:duration=longest:dropout_transition=0,"
        f"atrim=0:{_ffmpeg_seconds(duration)}[aout]"
    )
    return "aout"


def _eq_filter(effects: dict) -> str:
    brightness = max(-1.0, min(1.0, float(effects.get("brightness", 1) or 1) - 1))
    contrast = max(0.0, min(4.0, float(effects.get("contrast", 1) or 1)))
    saturation = max(0.0, min(3.0, float(effects.get("saturation", 1) or 1)))
    if abs(brightness) < 0.001 and abs(contrast - 1) < 0.001 and abs(saturation - 1) < 0.001:
        return ""
    return f"eq=brightness={brightness:.4f}:contrast={contrast:.4f}:saturation={saturation:.4f}"


def _transition_duration_for_render(item: TimelineItem | None, scene_duration: float) -> float:
    if not item:
        return 0.0
    raw = item.style.get("duration_seconds") or item.source_ref.get("duration_seconds") or (item.end_seconds - item.start_seconds)
    return round(max(0.05, min(float(raw or 0.35), scene_duration - 0.05, 1.5)), 3)


def _ffmpeg_transition_id(item: TimelineItem) -> str:
    transition_id = item.style.get("transition_id") or item.source_ref.get("transition_id") or "fade"
    return {
        "clean_cut": "fade",
        "fade": "fade",
        "dissolve": "dissolve",
        "slide_left": "slideleft",
        "slide_right": "slideright",
        "slide_up": "slideup",
        "zoom_in": "zoomin",
        "zoom_out": "fade",
        "whip_pan": "smoothleft",
        "flash_cut": "fadewhite",
    }.get(str(transition_id), "fade")


def _ffmpeg_seconds(value: float) -> str:
    return f"{max(0.0, float(value)):.3f}"
