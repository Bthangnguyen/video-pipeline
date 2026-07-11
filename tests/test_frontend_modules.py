import re
from pathlib import Path


STATIC_DIR = Path(__file__).resolve().parents[1] / "app" / "static"
LOCAL_IMPORT = re.compile(r'''(?:from\s+|import\s*)["'](\.[^"']+)["']''')


def test_videodesign_local_module_imports_resolve():
    entrypoint = STATIC_DIR / "videodesign.js"
    modules = [entrypoint, *(STATIC_DIR / "videodesign").rglob("*.js")]

    for module in modules:
        source = module.read_text(encoding="utf-8")
        for reference in LOCAL_IMPORT.findall(source):
            target = (module.parent / reference).resolve()
            assert target.is_relative_to(STATIC_DIR.resolve())
            assert target.exists(), f"{module.name} imports missing module {reference}"


def test_videodesign_uses_module_entrypoint():
    html = (STATIC_DIR / "videodesign.html").read_text(encoding="utf-8")

    assert '<script type="module" src="/static/videodesign.js"></script>' in html
