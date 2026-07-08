import json

from fastapi.testclient import TestClient

from app.main import app
from app.pinterestsearch.cookies import cookie_header_from_file, load_cookies, parse_cookie_string
from app.pinterestsearch.parser import parse_dom_cards
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


def test_pinterest_missing_result_returns_result_expired():
    client = TestClient(app)

    response = client.get("/api/pinterest/results/not-found")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "RESULT_EXPIRED"


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
