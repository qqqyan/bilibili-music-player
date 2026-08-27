"""UP 主服务:搜索 UP 主、获取其投稿视频列表。"""

import asyncio

from bilibili_api import search, user

from ..config import get_credential
from ..models import SearchPage, TrackInfo
from .search_service import _video_search_item_to_track

_VIDEO_SOURCE = "bilibili 视频"


async def search_users(keyword: str, page: int = 1) -> list[dict]:
    """搜索 UP 主(全站用户搜索)。"""
    res = await search.search_by_type(
        keyword,
        search_type=search.SearchObjectType.USER,
        page=page,
        page_size=10,
    )
    raw_items = res.get("result") or []
    if not isinstance(raw_items, list):
        return []
    users = []
    for it in raw_items:
        mid = it.get("mid")
        if not mid:
            continue
        users.append(
            {
                "mid": mid,
                "name": it.get("uname", ""),
                "face": it.get("upic", ""),
                "fans": it.get("fans", 0),
                "videos": it.get("videos", 0),
                "sign": it.get("usign", ""),
            }
        )
    return users


async def get_user_profile(mid: int) -> dict:
    """UP 主信息(粉丝数来自关系统计接口,用户信息接口不含此字段)。"""
    u = user.User(uid=mid, credential=get_credential())
    info, relation = await asyncio.gather(u.get_user_info(), u.get_relation_info())
    info = info or {}
    relation = relation or {}
    return {
        "mid": mid,
        "name": info.get("name", ""),
        "face": info.get("face", ""),
        "sign": info.get("sign", ""),
        "fans": relation.get("follower", 0),
    }


async def get_user_videos(mid: int, page: int = 1) -> SearchPage:
    """UP 主投稿视频列表(按发布时间倒序,分页)。"""
    u = user.User(uid=mid, credential=get_credential())
    res = await u.get_videos(pn=page, ps=30, order=user.VideoOrder.PUBDATE)
    # 结构:{list: {vlist: [...]}, page: {count: N}}
    raw_items = (res.get("list") or {}).get("vlist") or []
    if not isinstance(raw_items, list):
        return SearchPage(items=[], has_more=False)
    items = [
        _video_search_item_to_track(it, source=_VIDEO_SOURCE)
        for it in raw_items
        if it.get("bvid")
    ]
    count = (res.get("page") or {}).get("count") or 0
    total_pages = (count + 29) // 30 if count else 1
    return SearchPage(items=items, has_more=page < total_pages)
