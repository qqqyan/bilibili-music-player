"""B站音频歌单(AudioList)导入服务。

歌单条目可能是:
  - 带 bvid 的视频(直接作为 bilibili 视频导入);
  - 纯音频(au{id},需要解析服务的 au 支持)。
"""

import asyncio

from bilibili_api import audio

from ..config import get_credential
from ..models import TrackInfo
from ._utils import abs_url


def _song_to_track(song: dict) -> TrackInfo | None:
    auid = int(song.get("id") or 0)
    if not auid:
        return None
    bvid = song.get("bvid") or ""
    is_video = bool(bvid)
    return TrackInfo(
        id=f"bv{bvid}" if is_video else f"au{auid}",
        title=song.get("title") or "",
        artist=song.get("author") or song.get("uname") or "",
        mid=int(song.get("uid") or 0),
        cover=abs_url(song.get("cover") or ""),
        duration=int(song.get("duration") or 0),
        source="bilibili 视频" if is_video else "bilibili 音频",
    )


async def get_list(am_id: int, page: int = 1) -> dict:
    """读取音频歌单信息与单页歌曲。"""
    audio_list = audio.AudioList(am_id, credential=get_credential())
    info, songs = await asyncio.gather(
        audio_list.get_info(), audio_list.get_song_list(page)
    )
    info = info or {}
    songs = songs or {}
    items = []
    for song in songs.get("data") or []:
        track = _song_to_track(song) if isinstance(song, dict) else None
        if track is not None:
            items.append(track)
    page_count = int(songs.get("pageCount") or 1)
    return {
        "am_id": am_id,
        "title": info.get("title") or f"B站歌单 {am_id}",
        "cover": abs_url(info.get("cover") or ""),
        "upper": info.get("uname") or "",
        "intro": info.get("intro") or "",
        "count": int(info.get("snum") or songs.get("totalSize") or 0),
        "page": page,
        "has_more": page < page_count,
        "items": items,
    }
