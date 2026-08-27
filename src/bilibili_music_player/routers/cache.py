"""缓存路由:下载队列 / 状态 / 本地流(兼容旧端点)/ 清理。"""

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ..repositories import cache_store
from ..services.download_manager import manager as download_manager

router = APIRouter(prefix="/api")


class QueueRequest(BaseModel):
    track_ids: list[str]
    priority: bool = False  # True 时插到队首(点播优先)
    force: bool = False  # True 时按期望档检查补下
    desired_audio_quality: int = -1  # 期望音质档 ID,-1 = 最高
    desired_video_quality: int = -1  # 期望画质档 ID,-1 = 最高


@router.post("/cache/queue")
async def api_cache_queue(req: QueueRequest):
    """批量加入下载队列(后台限频下载)。

    desired_* 指定期望档位(-1=最高):曲目没有该档时自动降级到其最好可用档。
    """
    await download_manager.enqueue(
        req.track_ids,
        priority=req.priority,
        force=req.force,
        desired_audio=req.desired_audio_quality,
        desired_video=req.desired_video_quality,
    )
    return {"queued": len(req.track_ids)}


@router.get("/cache/status/{track_id}")
async def api_cache_status(track_id: str):
    """单曲缓存状态(实时查磁盘)。"""
    return await download_manager.get_status(track_id)


@router.get("/cache")
async def api_cache_all():
    """全部缓存状态 + 缓存占用。"""
    return {
        "items": await download_manager.get_all_statuses(),
        "total_size": await cache_store.cache_size(),
    }


@router.get("/local/{track_id}")
async def api_local_stream(track_id: str, quality_id: int = Query(..., description="音质档 ID")):
    """播放本地缓存音频(兼容旧端点,新代码统一走 /api/play)。"""
    path = await cache_store.open_local_file(track_id, quality_id, "audio")
    if path is None:
        raise HTTPException(status_code=404, detail="本地无该音质档缓存")
    return FileResponse(path, media_type="audio/mp4")


@router.get("/local/{track_id}/video")
async def api_local_video(track_id: str, quality_id: int = Query(..., description="画质档 ID")):
    """播放本地缓存视频画面(兼容旧端点,新代码统一走 /api/play)。"""
    path = await cache_store.open_local_file(track_id, quality_id, "video")
    if path is None:
        raise HTTPException(status_code=404, detail="本地无该画质档缓存")
    return FileResponse(path, media_type="video/mp4")


@router.post("/cache/cleanup")
async def api_cache_cleanup():
    """遍历全部缓存,每首只保留音频/视频的最高档,删除更低档。"""
    removed = await cache_store.cleanup_all()
    return {"removed": removed}


@router.delete("/cache/{track_id}")
async def api_cache_delete(track_id: str):
    """删除单曲缓存。"""
    await cache_store.delete_track(track_id)
    await download_manager.refresh_local(track_id)
    return {"deleted": track_id}


@router.delete("/cache")
async def api_cache_clear():
    """清空全部本地缓存。"""
    await cache_store.clear_all()
    await download_manager.refresh_all()
    return {"cleared": True}
