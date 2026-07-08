import asyncio
from pathlib import Path
from urllib.parse import urlparse
import shutil

from app.videodesign.errors import DOWNLOAD_FAILED, VideoDesignError


class YtDlpDownloader:
    def __init__(self, executable: str | None = None):
        self.executable = executable

    async def download(
        self,
        url: str,
        output_path: Path,
        cookie_file: Path | None = None,
        cookie_header: str = "",
    ) -> Path:
        if not _is_http_url(url):
            raise VideoDesignError(DOWNLOAD_FAILED, f"yt-dlp download URL is invalid: {url}", retryable=True)
        executable = self.executable or shutil.which("yt-dlp")
        if not executable:
            raise VideoDesignError(DOWNLOAD_FAILED, "yt-dlp is not installed.", retryable=False)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = output_path.with_name(f"{output_path.stem}.yt-dlp{output_path.suffix}")
        if temp_path.exists():
            temp_path.unlink()

        args = [
            executable,
            "--no-playlist",
            "--force-overwrites",
            "--merge-output-format",
            "mp4",
            "--recode-video",
            "mp4",
            "-o",
            str(temp_path),
        ]
        if cookie_file and cookie_file.exists() and _looks_like_netscape(cookie_file):
            args.extend(["--cookies", str(cookie_file)])
        elif cookie_header:
            args.extend(["--add-header", f"Cookie: {cookie_header}"])
        args.append(url)

        process = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await process.communicate()
        if process.returncode != 0 or not temp_path.exists():
            if temp_path.exists():
                temp_path.unlink()
            message = stderr.decode("utf-8", errors="ignore").strip() or "yt-dlp failed to download video."
            raise VideoDesignError(DOWNLOAD_FAILED, f"yt-dlp download failed: {message}", retryable=True)

        if output_path.exists():
            output_path.unlink()
        temp_path.replace(output_path)
        return output_path


def _is_http_url(url: str) -> bool:
    parsed = urlparse(url or "")
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _looks_like_netscape(path: Path) -> bool:
    content = path.read_text(encoding="utf-8", errors="ignore")
    if "Netscape HTTP Cookie File" in content:
        return True
    for line in content.splitlines():
        if line.strip().startswith("#"):
            continue
        if len(line.split("\t")) >= 7:
            return True
    return False
