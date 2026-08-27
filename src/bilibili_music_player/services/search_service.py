"""搜索服务:全站视频搜索,统一为 TrackInfo 列表。"""

import re

from bilibili_api import search

from ..models import SearchPage, TrackInfo
from ._utils import abs_url, first, parse_duration, strip_em

# ---------------------------------------------------------------- 搜索

async def search_tracks(keyword: str, page: int = 1) -> SearchPage:
    """搜索 bilibili 视频(可作为音乐播放)。

    说明:音频区搜索接口 /x/mv/list 的 keyword 参数已失效(无论中英文均返回空),
    故搜索统一走全站视频搜索。
    """
    res = await search.search_by_type(
        keyword,
        search_type=search.SearchObjectType.VIDEO,
        page=page,
        page_size=20,
    )
    raw_items = res.get("result") or []
    if not isinstance(raw_items, list):
        return SearchPage(items=[], has_more=False)

    items = [
        _video_search_item_to_track(it, source="bilibili 视频")
        for it in raw_items
        if it.get("bvid")
    ]
    num_pages = res.get("numPages") or 1
    return SearchPage(items=items, has_more=page < num_pages)

def _video_search_item_to_track(it: dict, source: str) -> TrackInfo:
    return TrackInfo(
        id=f"bv{it['bvid']}",
        title=strip_em(first(it, "title", "name")),
        artist=first(it, "author", "uname", "up_name"),
        mid=int(it.get("mid") or 0),  # UP 主 ID(悬停预览/主页跳转)
        cover=abs_url(first(it, "pic", "cover")),
        duration=parse_duration(it.get("duration") or it.get("length")),
        source=source,
    )

