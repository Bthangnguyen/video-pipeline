import asyncio
import shutil
from pathlib import Path

from app.videodesign.config import settings
from app.videodesign.schemas import MaterialAsset


async def _create_preview_proxy(asset: MaterialAsset, aspect_ratio: str) -> Path | None:
    ffmpeg = shutil.which("ffmpeg")
    input_path = Path(asset.local_path)
    if not ffmpeg or not input_path.exists():
        return None
    width, height = _proxy_resolution(aspect_ratio)
    output_dir = settings.storage_dir / asset.project_id / "proxies"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{asset.asset_id}.mp4"
    temp_path = output_path.with_suffix(".tmp.mp4")
    if temp_path.exists():
        temp_path.unlink()
    vf = f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},fps=30"
    process = await asyncio.create_subprocess_exec(
        ffmpeg,
        "-y",
        "-i",
        str(input_path),
        "-an",
        "-vf",
        vf,
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "24",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        "-g",
        "60",
        str(temp_path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        await asyncio.wait_for(process.communicate(), timeout=180)
    except asyncio.TimeoutError:
        process.kill()
        await process.communicate()
        if temp_path.exists():
            temp_path.unlink()
        return None
    if process.returncode != 0 or not temp_path.exists():
        if temp_path.exists():
            temp_path.unlink()
        return None
    if output_path.exists():
        output_path.unlink()
    temp_path.replace(output_path)
    return output_path


async def _ensure_preview_proxy(asset: MaterialAsset, aspect_ratio: str) -> Path | None:
    if asset.proxy_path and Path(asset.proxy_path).exists():
        return Path(asset.proxy_path)
    proxy_path = await _create_preview_proxy(asset, aspect_ratio)
    if proxy_path:
        asset.proxy_path = str(proxy_path)
    return proxy_path


def _proxy_resolution(aspect_ratio: str) -> tuple[int, int]:
    if aspect_ratio == "16:9":
        return 1920, 1080
    if aspect_ratio == "1:1":
        return 1080, 1080
    return 1080, 1920
