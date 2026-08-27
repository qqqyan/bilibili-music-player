"""应用设置路由。"""

from fastapi import APIRouter

from ..repositories import settings_store

router = APIRouter(prefix="/api")


@router.get("/settings")
async def api_get_settings():
    """应用设置。"""
    return settings_store.load_settings()


@router.put("/settings")
async def api_save_settings(patch: dict):
    """合并保存设置(只更新传入字段)。"""
    return settings_store.save_settings(patch)
