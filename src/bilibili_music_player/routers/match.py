"""歌单匹配路由:导入/搜索控制/候选选择/批量入列。"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from ..services.match_service import (
    JobBusyError,
    NoJobError,
    SongNotFoundError,
    manager,
)

router = APIRouter(prefix="/api/match")


class ImportRequest(BaseModel):
    name: str
    content: str  # 网易云歌单 JSON 或匹配结果 JSONL(自动识别)
    source_platform: str = "netease"


class ChooseRequest(BaseModel):
    netease_id: int
    bvid: str | None = None  # None = 标记无匹配


class ApplyRequest(BaseModel):
    netease_ids: list[int]


class PlaceholderRequest(BaseModel):
    netease_ids: list[int] | None = None  # None = 全部歌曲


@router.get("/job")
async def api_get_job(summary: bool = Query(False)):
    """当前任务;summary=true 返回轻量字典(轮询用)。"""
    if summary:
        s = manager.get_summary()
        if s is None:
            raise HTTPException(status_code=404, detail="暂无匹配任务")
        return s
    job = manager.get_job()
    if job is None:
        raise HTTPException(status_code=404, detail="暂无匹配任务")
    return job


@router.post("/import")
async def api_import(req: ImportRequest):
    try:
        return await manager.import_job(req.name, req.content, req.source_platform)
    except JobBusyError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/start")
async def api_start():
    try:
        return await manager.start_search()
    except NoJobError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/pause")
async def api_pause():
    try:
        return await manager.pause()
    except NoJobError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/resume")
async def api_resume():
    try:
        return await manager.resume()
    except NoJobError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/reset")
async def api_reset():
    try:
        await manager.reset()
    except JobBusyError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"cleared": True}


@router.post("/choose")
async def api_choose(req: ChooseRequest):
    try:
        return await manager.choose(req.netease_id, req.bvid)
    except NoJobError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except SongNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/apply")
async def api_apply(req: ApplyRequest):
    try:
        return await manager.apply(req.netease_ids)
    except NoJobError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/placeholder")
async def api_placeholder(req: PlaceholderRequest):
    """把任务歌曲以占位条目加入播放列表(缺省全部;已存在跳过)。"""
    try:
        return await manager.add_placeholders(req.netease_ids)
    except NoJobError as e:
        raise HTTPException(status_code=404, detail=str(e))
