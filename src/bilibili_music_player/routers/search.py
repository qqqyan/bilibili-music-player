"""搜索路由。"""

from fastapi import APIRouter, HTTPException, Query

from ..services.search_service import search_tracks
from ..models import SearchPage

router = APIRouter(prefix="/api")


@router.get("/search", response_model=SearchPage)
async def api_search(
    keyword: str = Query(..., min_length=1, description="搜索关键词"),
    page: int = Query(1, ge=1),
    personalized: bool = Query(True, description="带登录凭证(个性化排序)"),
):
    """搜索全站视频,返回统一曲目列表。"""
    try:
        return await search_tracks(keyword, page, personalized)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
