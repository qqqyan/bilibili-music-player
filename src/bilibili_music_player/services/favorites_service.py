"""B站收藏夹导入服务。

两种入口:
  - 自己的收藏夹:登录后按当前 UID 拉取收藏夹列表;
  - 公开收藏夹:直接按 media_id 读取内容(未登录也可,用于分享链接导入)。
"""

from bilibili_api import favorite_list

from ..config import get_credential
from ..models import TrackInfo
from ._utils import abs_url

SOURCE = "bilibili 视频"


def current_mid() -> int | None:
    """当前登录账号 UID(未登录/异常返回 None)。"""
    try:
        return int(get_credential().dedeuserid or 0) or None
    except (TypeError, ValueError):
        return None


def _folder_to_item(folder: dict) -> dict:
    return {
        "media_id": int(folder.get("id") or 0),
        "fid": int(folder.get("fid") or 0),
        "title": folder.get("title") or "未命名收藏夹",
        "count": int(folder.get("media_count") or 0),
        "cover": abs_url(folder.get("cover") or ""),
    }


async def list_folders(mid: int | None = None) -> dict:
    """收藏夹列表:mid 为空时取当前登录账号,否则读指定用户的公开收藏夹。"""
    target = mid or current_mid()
    if not target:
        return {"logged_in": False, "mid": None, "items": []}
    data = await favorite_list.get_video_favorite_list(
        target, credential=get_credential()
    )
    raw = data.get("list") if isinstance(data, dict) else None
    items = [
        _folder_to_item(folder)
        for folder in (raw or [])
        if isinstance(folder, dict) and folder.get("id")
    ]
    return {"logged_in": current_mid() is not None, "mid": target, "items": items}


def _media_to_track(media: dict) -> TrackInfo | None:
    """收藏夹条目 → 播放列表曲目(只收视频,跳过失效/非视频条目)。"""
    bvid = media.get("bvid") or media.get("bv_id") or ""
    if not bvid or media.get("type") not in (None, 2):
        return None
    upper = media.get("upper") or {}
    return TrackInfo(
        id=f"bv{bvid}",
        title=media.get("title") or "",
        artist=upper.get("name") or "",
        mid=int(upper.get("mid") or 0),
        cover=abs_url(media.get("cover") or ""),
        duration=int(media.get("duration") or 0),
        source=SOURCE,
    )


async def list_items(media_id: int, page: int = 1) -> dict:
    """收藏夹内容(单页)。无效/不可见收藏夹抛出 ValueError。"""
    data = await favorite_list.get_video_favorite_list_content(
        media_id, page, credential=get_credential()
    )
    if not data:
        raise ValueError("收藏夹不存在或不可见")
    info = data.get("info") or {}
    items = []
    for media in data.get("medias") or []:
        track = _media_to_track(media) if isinstance(media, dict) else None
        if track is not None:
            items.append(track)
    return {
        "media": {
            "media_id": media_id,
            "title": info.get("title") or "",
            "count": int(info.get("media_count") or 0),
            "cover": abs_url(info.get("cover") or ""),
            "upper": (info.get("upper") or {}).get("name") or "",
        },
        "items": items,
        "has_more": bool(data.get("has_more")),
        "page": page,
    }
