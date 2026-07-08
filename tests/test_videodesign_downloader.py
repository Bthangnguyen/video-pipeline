import asyncio
from pathlib import Path

from app.videodesign.downloader import YtDlpDownloader


def test_ytdlp_downloader_builds_command(monkeypatch, tmp_path):
    calls = []

    class FakeProcess:
        returncode = 0

        async def communicate(self):
            Path(calls[0][calls[0].index("-o") + 1]).write_bytes(b"video")
            return b"", b""

    async def fake_create_subprocess_exec(*args, **kwargs):
        calls.append(list(args))
        return FakeProcess()

    cookie_file = tmp_path / "cookies.txt"
    cookie_file.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
    output_path = tmp_path / "scene.mp4"
    monkeypatch.setattr("app.videodesign.downloader.shutil.which", lambda name: "yt-dlp.exe")
    monkeypatch.setattr("app.videodesign.downloader.asyncio.create_subprocess_exec", fake_create_subprocess_exec)

    asyncio.run(YtDlpDownloader().download("https://www.pinterest.com/pin/123/", output_path, cookie_file))

    assert output_path.read_bytes() == b"video"
    assert calls[0][0] == "yt-dlp.exe"
    assert "--cookies" in calls[0]
    assert str(cookie_file) in calls[0]
    assert calls[0][-1] == "https://www.pinterest.com/pin/123/"


def test_ytdlp_downloader_uses_cookie_header_for_plain_cookie_file(monkeypatch, tmp_path):
    calls = []

    class FakeProcess:
        returncode = 0

        async def communicate(self):
            Path(calls[0][calls[0].index("-o") + 1]).write_bytes(b"video")
            return b"", b""

    async def fake_create_subprocess_exec(*args, **kwargs):
        calls.append(list(args))
        return FakeProcess()

    cookie_file = tmp_path / "cookies.txt"
    cookie_file.write_text("a=1", encoding="utf-8")
    output_path = tmp_path / "scene.mp4"
    monkeypatch.setattr("app.videodesign.downloader.shutil.which", lambda name: "yt-dlp.exe")
    monkeypatch.setattr("app.videodesign.downloader.asyncio.create_subprocess_exec", fake_create_subprocess_exec)

    asyncio.run(YtDlpDownloader().download("https://www.pinterest.com/pin/123/", output_path, cookie_file, "a=1"))

    assert "--cookies" not in calls[0]
    assert "--add-header" in calls[0]
    assert "Cookie: a=1" in calls[0]
