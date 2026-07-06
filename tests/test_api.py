from fastapi.testclient import TestClient

from app.main import app
from app.douyinsearch.schemas import DouyinResult
from app.douyinsearch.service import douyin_service


def test_health():
    client = TestClient(app)

    response = client.get("/api/douyin/health")

    assert response.status_code == 200
    assert response.json()["module"] == "douyinsearch"


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
