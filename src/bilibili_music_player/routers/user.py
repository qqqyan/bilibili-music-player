"""UP 主路由:搜索 UP 主、主页信息与投稿视频。"""

from fastapi import APIRouter, HTTPException, Query

from ..models import SearchPage
from ..services import user_service

router = APIRouter(prefix="/api")


@router.get("/users/search")
async def api_search_users(
    keyword: str = Query(..., min_length=1, description="搜索关键词"),
    page: int = Query(1, ge=1),
):
    """搜索 UP 主。"""
    try:
        return await user_service.search_users(keyword, page)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e)[:200])


@router.get("/user/{mid}/info")
async def api_user_info(mid: int):
    """UP 主信息(轻量,悬停预览用,不拉视频列表)。"""
    try:
        return await user_service.get_user_profile(mid)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"获取 UP 主信息失败: {str(e)[:120]}")


@router.get("/user/{mid}")
async def api_user_profile(
    mid: int,
    page: int = Query(1, ge=1, description="投稿视频页码"),
):
    """UP 主主页:信息 + 投稿视频(分页)。"""
    try:
        profile = await user_service.get_user_profile(mid)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"获取 UP 主信息失败: {str(e)[:120]}")
    try:
        videos = await user_service.get_user_videos(mid, page)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"获取投稿视频失败: {str(e)[:120]}")
    return {"user": profile, "videos": videos.items, "has_more": videos.has_more}
