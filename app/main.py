from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.douyin import router as douyin_router
from app.douyinsearch.service import douyin_service


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await douyin_service.close()


app = FastAPI(title="DouyinSearch", version="0.1.0", lifespan=lifespan)
app.include_router(douyin_router, prefix="/api/douyin", tags=["douyinsearch"])

static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/")
async def index():
    index_path = static_dir / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return {"module": "douyinsearch", "docs": "/docs"}

