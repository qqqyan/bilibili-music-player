"""FastAPI 服务:搜索 / 解析 / CDN 流代理。"""

from pathlib import Path

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import cache_store
from .bilibili_client import resolve_track, search_tracks
from .config import configure_client
from .download_manager import manager as download_manager
from .models import ResolvedTrack, SearchPage, TrackInfo
from .playlist_store import get_playlist, save_playlist
from .stream_proxy import prepare_stream


@asynccontextmanager
async def lifespan(_: FastAPI):
    # 事件循环内初始化 zoku 客户端:开启 curl_cffi 浏览器伪装
    configure_client()
    await download_manager.start()
    yield
    await download_manager.stop()


app = FastAPI(title="bilibili-music-player", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.get("/api/search", response_model=SearchPage)
async def api_search(
    keyword: str = Query(..., min_length=1, description="搜索关键词"),
    page: int = Query(1, ge=1),
):
    """搜索音频区与全站视频,返回统一曲目列表。"""
    try:
        return await search_tracks(keyword, page)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/resolve/{kind}/{track_id}", response_model=ResolvedTrack)
async def api_resolve(
    kind: str,
    track_id: str,
    page_index: int = Query(0, ge=0, description="视频分 P 序号,从 0 开始"),
):
    """解析曲目播放流(音频区直链 / 视频 DASH 音视频流)。"""
    if kind not in ("audio", "video"):
        raise HTTPException(status_code=400, detail=f"未知曲目类型: {kind}")
    try:
        return await resolve_track(kind, track_id, page_index)
    except ValueError as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/api/playlist", response_model=list[TrackInfo])
async def api_get_playlist():
    """获取歌单(data/playlist.json)。"""
    return await get_playlist()


@app.put("/api/playlist", response_model=list[TrackInfo])
async def api_save_playlist(items: list[TrackInfo]):
    """覆盖式保存歌单。"""
    await save_playlist([item.model_dump() for item in items])
    return items


class QueueRequest(BaseModel):
    track_ids: list[str]
    priority: bool = False  # True 时插到队首(点播优先)


@app.post("/api/cache/queue")
async def api_cache_queue(req: QueueRequest):
    """批量加入下载队列(后台串行限频下载,已有缓存自动跳过)。"""
    await download_manager.enqueue(req.track_ids, priority=req.priority)
    return {"queued": len(req.track_ids)}


@app.get("/api/cache/status/{track_id}")
async def api_cache_status(track_id: str):
    """单曲缓存状态(实时查磁盘)。"""
    return await download_manager.get_status(track_id)


@app.get("/api/cache")
async def api_cache_all():
    """全部缓存状态 + 缓存占用。"""
    return {
        "items": await download_manager.get_all_statuses(),
        "total_size": await cache_store.cache_size(),
    }


@app.get("/api/local/{track_id}")
async def api_local_stream(track_id: str, quality_id: int = Query(..., description="音质档 ID")):
    """播放本地缓存文件(支持 Range,拖动进度条)。"""
    path = await cache_store.open_local_file(track_id, quality_id)
    if path is None:
        raise HTTPException(status_code=404, detail="本地无该音质档缓存")
    return FileResponse(path, media_type="audio/mp4")


@app.delete("/api/cache/{track_id}")
async def api_cache_delete(track_id: str):
    """删除单曲缓存。"""
    await cache_store.delete_track(track_id)
    await download_manager.refresh_local(track_id)
    return {"deleted": track_id}


@app.delete("/api/cache")
async def api_cache_clear():
    """清空全部本地缓存。"""
    await cache_store.clear_all()
    await download_manager.refresh_all()
    return {"cleared": True}


@app.get("/api/stream/{token}")
async def api_stream(token: str, request: Request):
    """代理 CDN 流:透传 Range,候选 CDN 依次回退。"""
    range_header = request.headers.get("range")
    status, headers, body = await prepare_stream(token, range_header)
    return StreamingResponse(body, status_code=status, headers=headers)


# 前端构建产物(web/dist 存在时由后端直接托管)
_DIST = Path(__file__).resolve().parent.parent.parent / "web" / "dist"
if _DIST.exists():
    app.mount("/", StaticFiles(directory=_DIST, html=True), name="web")
