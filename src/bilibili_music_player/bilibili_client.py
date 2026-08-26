"""bilibili 音频/视频获取封装(基于本地 fork 的 bilibili-api-zoku)。

职责:
  - 搜索:音频区(音乐视频)+ 全站视频,统一为 TrackInfo 列表
  - 解析:音频区直链 / 视频 DASH 音视频流(多音质档 + MV 画面)
"""

import asyncio
import re

# 解析并发上限:批量点歌时避免对 bilibili 接口简单并发,防止触发风控限流。
# (播放策略之一:后端请求频控)
_RESOLVE_SEMAPHORE = asyncio.Semaphore(2)

from bilibili_api import audio, search, video
from bilibili_api.video import (
    AudioQuality,
    AudioStreamDownloadURL,
    FLVStreamDownloadURL,
    MP4StreamDownloadURL,
    VideoCodecs,
    VideoDownloadURLDataDetecter,
    VideoQuality,
    VideoStreamDownloadURL,
)

from .config import get_credential
from .models import ResolvedTrack, SearchPage, StreamInfo, TrackInfo
from .stream_proxy import REFERER, BROWSER_UA, register_stream, stream_token_url

AUDIO_QUALITY_LABELS = {
    AudioQuality._64K: "64K",
    AudioQuality._132K: "132K",
    AudioQuality._192K: "192K",
    AudioQuality.HI_RES: "Hi-Res",
    AudioQuality.DOLBY: "杜比",
}
# 音质排序(低 -> 高)
AUDIO_QUALITY_ORDER = [
    AudioQuality._64K,
    AudioQuality._132K,
    AudioQuality._192K,
    AudioQuality.HI_RES,
    AudioQuality.DOLBY,
]


# ---------------------------------------------------------------- 工具函数

def _abs_url(url: str) -> str:
    """补全协议头(B 站接口常返回 //host/path)。"""
    if not url:
        return ""
    return url if url.startswith("http") else f"https:{url}"


def _strip_em(text: str) -> str:
    """去掉搜索结果标题里的 <em class="keyword"> 高亮标签。"""
    return re.sub(r"</?em[^>]*>", "", text or "")


def _parse_duration(value) -> int:
    """时长归一化为秒:支持 "mm:ss" / "hh:mm:ss" / 数字秒。"""
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str) and ":" in value:
        parts = [int(p) for p in value.split(":")]
        secs = 0
        for p in parts:
            secs = secs * 60 + p
        return secs
    return 0


def _first(data: dict, *keys, default=""):
    """按候选键名依次取值。"""
    for key in keys:
        if data.get(key) not in (None, ""):
            return data[key]
    return default


# 视频编码兼容性排序:AVC(H.264)浏览器最兼容,同画质时排到更高优先级
_CODEC_RANK = {
    VideoCodecs.AVC: 0,
    VideoCodecs.AV1: 1,
    VideoCodecs.HEV: 2,
}


def _sort_video_streams(streams: list[VideoStreamDownloadURL]) -> list[VideoStreamDownloadURL]:
    """视频流排序:按画质从低到高;同画质 AVC 排最后(默认选中最兼容)。"""
    streams.sort(
        key=lambda s: (
            s.video_quality.value,
            -_CODEC_RANK.get(s.video_codecs, 3),
        )
    )
    return streams


def _make_stream_info(quality_id: int, quality: str, mime: str, bandwidth: int,
                      urls: list[str]) -> StreamInfo:
    """把一组候选 CDN URL 注册为代理 token,包装为 StreamInfo。"""
    token = register_stream(urls)
    return StreamInfo(
        quality_id=quality_id,
        quality=quality,
        mime=mime or "application/octet-stream",
        bandwidth=bandwidth or 0,
        stream_url=stream_token_url(token),
    )


def _stream_urls(*streams) -> list[str]:
    """收集流的主 URL 与备用 URL,去重。"""
    urls: list[str] = []
    for s in streams:
        if s is None:
            continue
        for u in [s.url, *getattr(s, "backup_url", [])]:
            if u and u not in urls:
                urls.append(u)
    return urls


# ---------------------------------------------------------------- 搜索

async def search_tracks(keyword: str, page: int = 1) -> SearchPage:
    """搜索 bilibili 视频(可作为音乐播放)。

    说明:音频区搜索接口 /x/mv/list 的 keyword 参数已失效(无论中英文均返回空),
    故搜索统一走全站视频搜索;音频区 AU 号的解析能力保留在 resolve_track,供后续
    导入 B 站歌单(AudioList)时使用。
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
        kind="video",
        title=_strip_em(_first(it, "title", "name")),
        artist=_first(it, "author", "uname", "up_name"),
        cover=_abs_url(_first(it, "pic", "cover")),
        duration=_parse_duration(it.get("duration")),
        source=source,
    )


# ---------------------------------------------------------------- 解析

async def resolve_track(kind: str, track_id: str, page_index: int = 0) -> ResolvedTrack:
    """解析曲目播放流。kind: audio(au{auid}) / video(bv{bvid})。

    经信号量限频:并发解析不超过 2 个,超出排队(防批量操作触发风控)。
    """
    async with _RESOLVE_SEMAPHORE:
        if kind == "audio":
            return await _resolve_audio(int(track_id.removeprefix("au")))
        if kind == "video":
            return await _resolve_video(track_id.removeprefix("bv"), page_index)
    raise ValueError(f"未知曲目类型: {kind}")


async def _resolve_audio(auid: int) -> ResolvedTrack:
    """音频区:Audio.get_download_url 直接给出 CDN 直链(单音质档)。"""
    cred = get_credential()
    a = audio.Audio(auid, credential=cred)
    info, url_data = await asyncio.gather(a.get_info(), a.get_download_url())
    data = info or {}  # Api.result 已提取 data 字段
    cdns = url_data.get("cdns") or []
    if not cdns:
        raise ValueError("未获取到音频流 URL(可能需登录或已下架)")
    stream = _make_stream_info(
        quality_id=0,
        quality="标准",  # 音频区音质由接口固定(quality=2),不可选
        mime="audio/mp4",
        bandwidth=0,
        urls=cdns,
    )
    return ResolvedTrack(
        id=f"au{auid}",
        kind="audio",
        title=_first(data, "title", "name"),
        artist=_first(data, "uname", "author"),
        cover=_abs_url(_first(data, "cover", "pic")),
        duration=_parse_duration(data.get("duration")),
        source="bilibili 音频区",
        audio_streams=[stream],
    )


async def _resolve_video(bvid: str, page_index: int) -> ResolvedTrack:
    """视频:解析 DASH 音视频流,提供多音质档 + MV 画面。"""
    cred = get_credential()
    v = video.Video(bvid=bvid, credential=cred)
    info, url_data = await asyncio.gather(
        v.get_info(), v.get_download_url(page_index=page_index)
    )
    data = info or {}  # Api.result 已提取 data 字段
    pages = data.get("pages") or []
    page = pages[page_index] if 0 <= page_index < len(pages) else {}

    detecter = VideoDownloadURLDataDetecter(url_data)

    # 单文件流(FLV/MP4):音视频一体,音频与画面同源
    if detecter.check_flv_mp4_stream():
        streams = detecter.detect_all()
        if streams and isinstance(streams[0], MP4StreamDownloadURL):
            # MP4 单文件:<video> 直接播放(音画一体)
            stream = _make_stream_info(
                0, "标准", "video/mp4", 0, _stream_urls(streams[0])
            )
            track = _build_video_track(data, page, bvid)
            track.audio_streams = [stream]
            track.video_streams = [stream]  # 同一文件即音画
            return track
        if streams and isinstance(streams[0], FLVStreamDownloadURL):
            # FLV 浏览器无法原生播放,尝试 html5 MP4 流
            html5_data = await v.get_download_url(page_index=page_index, html5=True)
            html5_detecter = VideoDownloadURLDataDetecter(html5_data)
            html5_streams = html5_detecter.detect_all()
            if html5_streams and isinstance(html5_streams[0], MP4StreamDownloadURL):
                stream = _make_stream_info(
                    0, "标准", "video/mp4", 0, _stream_urls(html5_streams[0])
                )
                track = _build_video_track(data, page, bvid)
                track.audio_streams = [stream]
                track.video_streams = [stream]
                return track
            raise ValueError("该视频仅有 FLV 流,暂不支持播放")

    # DASH 音视频分离流:音频/视频各自为 peer,独立返回档位列表
    all_streams = detecter.detect()
    audio_streams = [s for s in all_streams if isinstance(s, AudioStreamDownloadURL)]
    video_streams = [s for s in all_streams if isinstance(s, VideoStreamDownloadURL)]
    if not audio_streams:
        raise ValueError("未获取到音频流(可能需登录或该视频不支持)")

    audio_streams.sort(
        key=lambda s: AUDIO_QUALITY_ORDER.index(s.audio_quality)
        if s.audio_quality in AUDIO_QUALITY_ORDER else 0
    )
    track = _build_video_track(data, page, bvid)
    track.audio_streams = [
        _make_stream_info(
            quality_id=s.audio_quality.value,
            quality=AUDIO_QUALITY_LABELS.get(s.audio_quality, "未知"),
            mime=s.mime_type,
            bandwidth=s.bandwidth,
            urls=_stream_urls(s),
        )
        for s in audio_streams
    ]
    track.video_streams = [
        _make_stream_info(
            quality_id=s.video_quality.value,
            quality=s.video_quality.name.lstrip("_"),
            mime=s.mime_type,
            bandwidth=s.bandwidth,
            urls=_stream_urls(s),
        )
        for s in _sort_video_streams(video_streams)
    ]
    return track


def _build_video_track(data: dict, page: dict, bvid: str) -> ResolvedTrack:
    """从视频信息构造元数据(标题取分 P 标题)。"""
    title = page.get("part") or data.get("title") or ""
    if len(data.get("pages") or []) > 1 and page.get("part"):
        title = f"{data.get('title', '')} - {page['part']}"
    return ResolvedTrack(
        id=f"bv{bvid}",
        kind="video",
        title=title,
        artist=_first(data.get("owner") or {}, "name", "uname"),
        cover=_abs_url(page.get("first_frame") or data.get("pic") or ""),
        duration=_parse_duration(page.get("duration") or data.get("duration")),
        source="bilibili 视频",
        audio_streams=[],
    )
