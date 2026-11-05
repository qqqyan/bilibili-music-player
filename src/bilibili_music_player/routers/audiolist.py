"""B站音频歌单路由:读取歌单信息与歌曲列表。"""

from fastapi import APIRouter, HTTPException, Query

from ..services import audio_list_service

router = APIRouter(prefix="/api")


@router.get("/audiolist/{am_id}")
async def api_audiolist(
    am_id: int,
    page: int = Query(1, ge=1, description="歌单歌曲页码(每页 100 首)"),
):
    """音频歌单信息 + 单页歌曲(条目已映射为播放列表曲目)。"""
    try:
        return await audio_list_service.get_list(am_id, page)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"获取 B站歌单失败: {str(e)[:120]}")
