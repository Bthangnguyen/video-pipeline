import asyncio

from app.douyinsearch.browser_client import BrowserClient
from fastapi.testclient import TestClient

from app.main import app
from app.douyinsearch.schemas import DouyinResult
from app.douyinsearch.service import douyin_service


def test_health():
    client = TestClient(app)

    response = client.get("/api/douyin/health")

    assert response.status_code == 200
    assert response.json()["module"] == "douyinsearch"


def test_douyin_preflight_missing_cookie_file(tmp_path):
    result = asyncio.run(BrowserClient(tmp_path / "missing.txt", True, False).preflight_check())

    assert result["success"] is False
    assert result["state"] == "missing_cookie_file"
    assert result["checks"][0]["name"] == "cookie_file"


def test_videodesign_page():
    client = TestClient(app)

    response = client.get("/videodesign")

    assert response.status_code == 200
    assert "VideoDesign" in response.text


def test_direct_api_stub():
    client = TestClient(app)

    response = client.post(
        "/api/douyin/search",
        json={"keyword": "test", "translate_to_chinese": False, "strategy": "direct_api"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "DIRECT_API_FAILED"


def test_missing_result_returns_result_expired():
    client = TestClient(app)

    response = client.get("/api/douyin/results/not-found")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "RESULT_EXPIRED"


def test_stream_endpoint_forwards_range(monkeypatch):
    client = TestClient(app)
    douyin_service.store.put_many(
        [
            DouyinResult(
                result_id="stream-test",
                douyin_aweme_id="aweme",
                stream_remote_url="https://example.test/video.mp4",
            )
        ]
    )

    async def fake_proxy_stream(result, range_header=None):
        assert result.douyin_aweme_id == "aweme"
        assert range_header == "bytes=0-10"
        from fastapi.responses import Response

        return Response(content=b"video", media_type="video/mp4", status_code=206)

    monkeypatch.setattr(douyin_service.stream_proxy, "proxy_stream", fake_proxy_stream)

    response = client.get("/api/douyin/results/stream-test/stream", headers={"Range": "bytes=0-10"})

    assert response.status_code == 206
    assert response.content == b"video"


def test_download_endpoint_returns_attachment(monkeypatch):
    client = TestClient(app)
    douyin_service.store.put_many(
        [
            DouyinResult(
                result_id="download-test",
                douyin_aweme_id="aweme-download",
                raw={"video": {"play_addr": {"uri": "video-uri", "url_list": ["https://example.test/playwm/video.mp4"]}}},
            )
        ]
    )

    async def fake_proxy_download(result):
        assert result.douyin_aweme_id == "aweme-download"
        from fastapi.responses import Response

        return Response(
            content=b"video",
            media_type="video/mp4",
            headers={"content-disposition": 'attachment; filename="douyin_aweme-download.mp4"'},
        )

    monkeypatch.setattr(douyin_service.stream_proxy, "proxy_download", fake_proxy_download)

    response = client.get("/api/douyin/results/download-test/download")

    assert response.status_code == 200
    assert response.headers["content-disposition"] == 'attachment; filename="douyin_aweme-download.mp4"'
    assert response.content == b"video"
