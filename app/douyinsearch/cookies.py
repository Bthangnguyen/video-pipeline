import json
from pathlib import Path
from typing import Any


def cookie_header_from_file(path: Path) -> str:
    content = path.read_text(encoding="utf-8").strip()
    if not content:
        return ""
    if _looks_like_netscape_cookie_file(content):
        cookies = parse_netscape_cookie_file(content)
        return "; ".join(f"{cookie['name']}={cookie['value']}" for cookie in cookies if cookie.get("name"))
    if not (content.startswith("{") or content.startswith("[")):
        return content
    cookies = load_cookies(path)
    return "; ".join(f"{cookie['name']}={cookie['value']}" for cookie in cookies if cookie.get("name"))


def load_cookies(path: Path) -> list[dict[str, Any]]:
    content = path.read_text(encoding="utf-8").strip()
    if not content:
        return []
    if _looks_like_netscape_cookie_file(content):
        return parse_netscape_cookie_file(content)
    if content.startswith("{") or content.startswith("["):
        data = json.loads(content)
        if isinstance(data, dict) and isinstance(data.get("cookies"), list):
            data = data["cookies"]
        if isinstance(data, dict):
            data = [data]
        return [_normalize_cookie(cookie) for cookie in data if isinstance(cookie, dict) and cookie.get("name")]
    return parse_cookie_string(content)


def parse_netscape_cookie_file(content: str) -> list[dict[str, Any]]:
    cookies: list[dict[str, Any]] = []
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or (line.startswith("#") and not line.startswith("#HttpOnly_")):
            continue
        http_only = line.startswith("#HttpOnly_")
        if http_only:
            line = line.removeprefix("#HttpOnly_")
        parts = line.split("\t")
        if len(parts) < 7:
            continue
        domain, _include_subdomains, path, secure, expires, name, value = parts[:7]
        cookie: dict[str, Any] = {
            "name": name,
            "value": value,
            "domain": domain,
            "path": path or "/",
            "secure": secure.upper() == "TRUE",
            "httpOnly": http_only,
            "sameSite": "Lax",
        }
        try:
            expires_value = int(expires)
            if expires_value > 0:
                cookie["expires"] = expires_value
        except ValueError:
            pass
        cookies.append(cookie)
    return cookies


def parse_cookie_string(cookie_string: str) -> list[dict[str, Any]]:
    cookies: list[dict[str, Any]] = []
    for part in cookie_string.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        name, value = part.split("=", 1)
        cookies.append(
            {
                "name": name.strip(),
                "value": value.strip(),
                "domain": ".douyin.com",
                "path": "/",
                "secure": True,
                "httpOnly": False,
                "sameSite": "Lax",
            }
        )
    return cookies


def _looks_like_netscape_cookie_file(content: str) -> bool:
    if "Netscape HTTP Cookie File" in content:
        return True
    for line in content.splitlines():
        if line.strip().startswith("#"):
            continue
        if len(line.split("\t")) >= 7:
            return True
    return False


def _normalize_cookie(cookie: dict[str, Any]) -> dict[str, Any]:
    same_site = cookie.get("sameSite", cookie.get("same_site", "Lax"))
    if same_site not in {"Strict", "Lax", "None"}:
        same_site = "Lax"
    return {
        "name": str(cookie.get("name", "")),
        "value": str(cookie.get("value", "")),
        "domain": cookie.get("domain") or ".douyin.com",
        "path": cookie.get("path") or "/",
        "secure": bool(cookie.get("secure", True)),
        "httpOnly": bool(cookie.get("httpOnly", cookie.get("http_only", False))),
        "sameSite": same_site,
    }
