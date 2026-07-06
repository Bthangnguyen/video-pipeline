import json

from app.douyinsearch.cookies import (
    cookie_header_from_file,
    load_cookies,
    parse_cookie_string,
    parse_netscape_cookie_file,
)


def test_parse_plain_cookie_string():
    cookies = parse_cookie_string("a=1; b=hello")

    assert [cookie["name"] for cookie in cookies] == ["a", "b"]
    assert cookies[0]["domain"] == ".douyin.com"


def test_load_exported_cookie_json(tmp_path):
    path = tmp_path / "cookies.json"
    path.write_text(json.dumps([{"name": "sid", "value": "abc", "domain": ".douyin.com"}]), encoding="utf-8")

    cookies = load_cookies(path)

    assert cookies[0]["name"] == "sid"
    assert cookies[0]["sameSite"] == "Lax"


def test_load_playwright_storage_state(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"cookies": [{"name": "sid", "value": "abc"}]}), encoding="utf-8")

    assert cookie_header_from_file(path) == "sid=abc"


def test_parse_netscape_cookie_file():
    content = "\n".join(
        [
            "# Netscape HTTP Cookie File",
            ".douyin.com\tTRUE\t/\tTRUE\t1817056288\tsid\tabc",
            "#HttpOnly_.douyin.com\tTRUE\t/\tFALSE\t0\thid\tsecret",
        ]
    )

    cookies = parse_netscape_cookie_file(content)

    assert [cookie["name"] for cookie in cookies] == ["sid", "hid"]
    assert cookies[0]["expires"] == 1817056288
    assert cookies[1]["httpOnly"] is True
