"""曲目路由:解析 / 播放决策(plan) / 统一播放端点 / 档位列表 / 流代理。"""

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, StreamingResponse

from ..repositories import cache_store
from .. import quality
from ..quality import pick_stream_by_quality
from ..services.parse_service import resolve_track
from ..services.download_manager import manager as download_manager
from ..models import ResolvedTrack
from ..quality import order_of
from ..services.stream_proxy import prepare_stream

router = APIRouter(prefix="/api")


@router.get("/resolve/{track_id}", response_model=ResolvedTrack)
async def api_resolve(
    track_id: str,
    page_index: int = Query(0, ge=0, description="视频分 P 序号,从 0 开始"),
):
    """解析 bilibili 视频播放流(DASH 音视频流)。"""
    try:
        return await resolve_track(track_id, page_index)
    except ValueError as e:
        raise HTTPException(status_code=502, detail=str(e))


def _merge_quality_list(local_quals: list[dict], remote_streams: list, kind: str) -> list[dict]:
    """合并本地档(带 local 标记,排前)+ 远程新档,按质量升序。"""
    mime = "video/mp4" if kind == "video" else "audio/mp4"
    merged = [
        {
            "quality_id": q["quality_id"],
            "quality": q["quality"],
            "mime": mime,
            "local": True,
        }
        for q in local_quals
    ]
    for s in remote_streams:
        if not any(m["quality_id"] == s.quality_id for m in merged):
            merged.append(
                {
                    "quality_id": s.quality_id,
                    "quality": s.quality,
                    "mime": s.mime or mime,
                    "local": False,
                }
            )
    merged.sort(key=lambda m: order_of(m["quality_id"], kind))
    return merged


@router.get("/track/{track_id}/plan")
async def api_track_plan(
    track_id: str,
    audio_quality: int = Query(-1, description="期望音质档 ID,-1=自动最高"),
    video_quality: int = Query(-1, description="期望画质档 ID,-1=自动最高"),
):
    """播放决策接口:合并档位列表 + 播放来源决策 + 补缓存决策。

    调用即视为「播放意图」:顺带把该曲目在下载队列中提队首(点播优先)。
    前端只按 play 决策播放、按 download 决策触发下载,无需感知本地/在线。
    """
    await download_manager.prioritize(track_id)
    resolved = await resolve_track(track_id)
    local_audio = await cache_store.get_local_qualities(track_id)
    local_video = await cache_store.get_local_videos(track_id)

    # 合并档位(本地在前带 local 标记)
    audio_streams = _merge_quality_list(local_audio, resolved.audio_streams, "audio")
    video_streams = _merge_quality_list(local_video, resolved.video_streams, "video")

    # play 决策:本地最高满足期望 → 本地最高;否则期望档(降级)走远程
    def decide_play(local_quals, remote_streams, desired, kind):
        if local_quals:
            best = local_quals[-1]
            if desired < 0 or order_of(best["quality_id"], kind) >= order_of(desired, kind):
                return best["quality_id"], True
        stream = pick_stream_by_quality(remote_streams, desired, kind)
        return (stream.quality_id, False) if stream is not None else (None, False)

    play_audio_q, play_audio_local = decide_play(
        local_audio, resolved.audio_streams, audio_quality, "audio"
    )
    play_video_q, play_video_local = (
        decide_play(local_video, resolved.video_streams, video_quality, "video")
        if resolved.video_streams
        else (None, False)
    )

    # download 决策:本地最高低于期望档(降级后)→ 补期望档
    def decide_download(local_quals, remote_streams, desired, kind):
        if not remote_streams:
            return None
        want = pick_stream_by_quality(remote_streams, desired, kind)
        if want is None:
            return None
        if local_quals:
            best = local_quals[-1]
            if order_of(best["quality_id"], kind) >= order_of(want.quality_id, kind):
                return None  # 已满足
        return want.quality_id

    return {
        "track": {
            "id": resolved.id,
            "title": resolved.title,
            "artist": resolved.artist,
            "cover": resolved.cover,
            "duration": resolved.duration,
            "source": resolved.source,
        },
        "audio_streams": audio_streams,
        "video_streams": video_streams,
        "play": {
            "audio_quality": play_audio_q,
            "audio_local": play_audio_local,
            "video_quality": play_video_q,
            "video_local": play_video_local,
        },
        "download": {
            "audio": decide_download(local_audio, resolved.audio_streams, audio_quality, "audio"),
            "video": decide_download(local_video, resolved.video_streams, video_quality, "video"),
        },
    }


@router.get("/qualities")
async def api_qualities():
    """可选档位列表(下载弹窗等 UI 使用,由后端提供唯一事实来源)。"""
    return {
        "audio": [
            {"id": q, "label": quality.QUALITY_LABELS.get(q, str(q))}
            for q in quality.QUALITY_ORDER
        ],
        "video": [
            {"id": q, "label": label}
            for q, label in sorted(quality.VIDEO_QUALITY_LABELS.items())
        ],
    }


@router.get("/play/{track_id}")
async def api_play(
    track_id: str,
    request: Request,
    kind: str = Query("audio", pattern="^(audio|video)$"),
    quality_id: int = Query(-1, description="期望档 ID,-1=自动最高"),
):
    """统一播放端点:本地满足期望档 → 直接播本地文件;
    否则远程解析 + CDN 代理。前端无需感知来源。"""
    local_quals = (
        await cache_store.get_local_videos(track_id)
        if kind == "video"
        else await cache_store.get_local_qualities(track_id)
    )
    # 本地满足期望 → 播本地最高
    if local_quals:
        best = local_quals[-1]
        if quality_id < 0 or order_of(best["quality_id"], kind) >= order_of(
            quality_id, kind
        ):
            path = await cache_store.open_local_file(track_id, best["quality_id"], kind)
            if path is not None:
                media = "video/mp4" if kind == "video" else "audio/mp4"
                return FileResponse(path, media_type=media)
    # 远程:解析 + 选档 + 代理流
    resolved = await resolve_track(track_id)
    streams = resolved.video_streams if kind == "video" else resolved.audio_streams
    stream = pick_stream_by_quality(streams, quality_id, kind)
    if stream is None:
        raise HTTPException(status_code=404, detail="该曲目无此类型流")
    token = stream.stream_url.rsplit("/", 1)[-1]
    range_header = request.headers.get("range")
    status, headers, body = await prepare_stream(token, range_header)
    return StreamingResponse(body, status_code=status, headers=headers)


@router.get("/stream/{token}")
async def api_stream(token: str, request: Request):
    """代理 CDN 流:透传 Range,候选 CDN 依次回退。"""
    range_header = request.headers.get("range")
    status, headers, body = await prepare_stream(token, range_header)
    return StreamingResponse(body, status_code=status, headers=headers)
