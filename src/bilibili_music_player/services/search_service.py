"""搜索服务:全站视频搜索,统一为 TrackInfo 列表。"""

import re

from bilibili_api.utils.network import Api
from bilibili_api.utils.utils import get_api

from ..config import get_credential
from ..models import SearchPage, TrackInfo
from ._utils import abs_url, first, parse_duration, strip_em

# ---------------------------------------------------------------- 搜索

async def search_tracks(keyword: str, page: int = 1, personalized: bool = True) -> SearchPage:
    """搜索 bilibili 视频(可作为音乐播放)。

    说明:
      - 音频区搜索接口 /x/mv/list 的 keyword 参数已失效,统一走全站视频搜索
      - personalized=True 时带登录凭证请求(个性化排序,与官网结果一致;
        实测匿名搜索会漏掉不少内容);zoku 的 search_by_type 不传凭证,
        故直接调 Api
    """
    api = get_api("search")["search"]["web_search_by_type"]
    params = {"keyword": keyword, "page": page, "page_size": 20, "search_type": "video"}
    credential = get_credential() if personalized else None
    res = await (
        Api(**api, wbi=True, credential=credential)
        .update_params(**params)
        .result
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

