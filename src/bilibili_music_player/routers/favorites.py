"""收藏夹路由:自己的收藏夹列表 + 收藏夹内容(公开可读)。"""

from fastapi import APIRouter, HTTPException, Query

from ..services import favorites_service

router = APIRouter(prefix="/api")


@router.get("/favorites/folders")
async def api_folders(mid: int | None = Query(None, ge=1, description="指定用户 UID(公开收藏夹)")):
    """收藏夹列表。不传 mid 时使用当前登录账号,未登录返回空列表。"""
    try:
        return await favorites_service.list_folders(mid)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"获取收藏夹失败: {str(e)[:120]}")


@router.get("/favorites/{media_id}/items")
async def api_items(
    media_id: int,
    page: int = Query(1, ge=1, description="收藏夹内容页码"),
):
    """收藏夹内容(单页);公开收藏夹无需登录。"""
    try:
        return await favorites_service.list_items(media_id, page)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"获取收藏夹内容失败: {str(e)[:120]}")
