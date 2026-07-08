from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.douyin import router as douyin_router
from app.api.pinterest import router as pinterest_router
from app.api.videodesign import router as videodesign_router
from app.douyinsearch.service import douyin_service
from app.pinterestsearch.service import pinterest_service


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await douyin_service.close()
    await pinterest_service.close()


app = FastAPI(title="DouyinSearch", version="0.1.0", lifespan=lifespan)
app.include_router(douyin_router, prefix="/api/douyin", tags=["douyinsearch"])
app.include_router(pinterest_router, prefix="/api/pinterest", tags=["pinterestsearch"])
app.include_router(videodesign_router, prefix="/api/videodesign", tags=["videodesign"])

static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/")
async def index():
    index_path = static_dir / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return {"module": "douyinsearch", "docs": "/docs"}


@app.get("/videodesign")
async def videodesign_index():
    index_path = static_dir / "videodesign.html"
    if index_path.exists():
        return FileResponse(index_path)
    return {"module": "videodesign", "docs": "/docs"}
