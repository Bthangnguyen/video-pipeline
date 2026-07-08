import json

from fastapi.testclient import TestClient

from app.main import app
from app.pinterestsearch.cookies import cookie_header_from_file, load_cookies, parse_cookie_string
from app.pinterestsearch.media_proxy import MediaProxy
from app.pinterestsearch.parser import parse_api_payloads, parse_dom_cards
from app.pinterestsearch.service import pinterest_service


def test_pinterest_health():
    client = TestClient(app)

    response = client.get("/api/pinterest/health")

    assert response.status_code == 200
    assert response.json()["module"] == "pinterestsearch"


def test_pinterest_cookie_plain_string():
    cookies = parse_cookie_string("a=1; b=hello")

    assert [cookie["name"] for cookie in cookies] == ["a", "b"]
    assert cookies[0]["domain"] == ".pinterest.com"


def test_pinterest_cookie_storage_state(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"cookies": [{"name": "_pinterest_sess", "value": "abc"}]}), encoding="utf-8")

    cookies = load_cookies(path)

    assert cookies[0]["name"] == "_pinterest_sess"
    assert cookie_header_from_file(path) == "_pinterest_sess=abc"


def test_parse_pinterest_cards_filters_video_vertical():
    cards = [
        {
            "href": "https://www.pinterest.com/pin/123/",
            "title": "vertical workout",
            "video_url": "https://v.pinimg.com/video.mp4",
            "image_url": "https://i.pinimg.com/cover.jpg",
            "width": 720,
            "height": 1280,
        },
        {
            "href": "https://www.pinterest.com/pin/456/",
            "title": "wide image",
            "image_url": "https://i.pinimg.com/image.jpg",
            "width": 1280,
            "height": 720,
        },
    ]

    results = parse_dom_cards(cards, limit=10, media_type="video", aspect_ratio="9:16", tolerance=0.1)

    assert len(results) == 1
    assert results[0].pin_id == "123"
    assert results[0].media_type == "video"
    assert results[0].aspect_ratio == "9:16"


def test_parse_pinterest_api_payload_extracts_video_metadata():
    payload = {
        "resource_response": {
            "data": {
                "results": [
                    {
                        "id": "123",
                        "description": "vertical cat video",
                        "pinner": {"full_name": "Cat Channel", "username": "cats"},
                        "images": {
                            "orig": {
                                "url": "https://i.pinimg.com/originals/cover.jpg",
                                "width": 576,
                                "height": 1024,
                            }
                        },
                        "videos": {
                            "video_list": {
                                "V_HLSV4": {
                                    "url": "https://v1.pinimg.com/videos/video.m3u8",
                                    "width": 576,
                                    "height": 1024,
                                    "thumbnail": "https://i.pinimg.com/videos/cover.jpg",
                                }
                            }
                        },
                    }
                ]
            }
        }
    }

    results = parse_api_payloads([payload], limit=10, media_type="video", aspect_ratio="9:16", tolerance=0.1)

    assert len(results) == 1
    assert results[0].pin_id == "123"
    assert results[0].media_type == "video"
    assert results[0].media_remote_url.endswith(".m3u8")
    assert results[0].cover_remote_url.endswith("cover.jpg")


def test_pinterest_missing_result_returns_result_expired():
    client = TestClient(app)

    response = client.get("/api/pinterest/results/not-found")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "RESULT_EXPIRED"


def test_pinterest_hls_playlist_rewrites_relative_urls(tmp_path):
    proxy = MediaProxy(tmp_path / "cookies.txt")
    playlist = '#EXTM3U\n#EXT-X-MEDIA:TYPE=AUDIO,URI="audio.m3u8"\nvideo_720w.m3u8\n'

    rewritten = proxy._rewrite_hls_playlist(
        playlist,
        "https://v1.pinimg.com/videos/iht/hls/a/b/root.m3u8",
        "pinr_test",
    )

    assert "/api/pinterest/results/pinr_test/media?url=" in rewritten
    assert "https%3A%2F%2Fv1.pinimg.com%2Fvideos%2Fiht%2Fhls%2Fa%2Fb%2Faudio.m3u8" in rewritten
    assert "https%3A%2F%2Fv1.pinimg.com%2Fvideos%2Fiht%2Fhls%2Fa%2Fb%2Fvideo_720w.m3u8" in rewritten


def test_pinterest_missing_cookie_file(monkeypatch, tmp_path):
    client = TestClient(app)
    original = pinterest_service.browser.cookie_file
    monkeypatch.setattr(pinterest_service.browser, "cookie_file", tmp_path / "missing.txt")

    response = client.post(
        "/api/pinterest/search",
        json={"keyword": "cat", "media_type": "video", "aspect_ratio": "9:16"},
    )

    monkeypatch.setattr(pinterest_service.browser, "cookie_file", original)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "MISSING_COOKIE_FILE"
