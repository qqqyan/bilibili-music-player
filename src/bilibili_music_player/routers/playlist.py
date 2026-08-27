"""歌单路由。"""

from fastapi import APIRouter

from ..models import TrackInfo
from ..repositories.playlist_store import get_playlist, save_playlist

router = APIRouter(prefix="/api")


@router.get("/playlist", response_model=list[TrackInfo])
async def api_get_playlist():
    """获取歌单(data/playlist.json)。"""
    return await get_playlist()


@router.put("/playlist", response_model=list[TrackInfo])
async def api_save_playlist(items: list[TrackInfo]):
    """覆盖式保存歌单。"""
    await save_playlist([item.model_dump() for item in items])
    return items
