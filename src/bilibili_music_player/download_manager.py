"""后台下载队列管理器。

原则(防触发 bilibili 风控):
  - 单 worker 串行下载,任务之间固定间隔
  - 批量加入按顺序排队;点播的曲目可提到队首优先下载
  - 失败自动重试,重试仍失败标记 failed 供前端提示/手动重试
"""

import asyncio
import os
from collections import deque

import httpx

from . import cache_store
from .bilibili_client import resolve_track
from .stream_proxy import BROWSER_UA, REFERER, get_stream_urls

# 下载任务之间的固定间隔(秒),避免连续请求触发风控
TASK_INTERVAL = 1.5
# 失败重试次数(不含首次)
RETRY_TIMES = 1


class DownloadManager:
    def __init__(self) -> None:
        self._queue: deque[str] = deque()
        self._states: dict[str, dict] = {}
        # track_id -> 本地已缓存档位(启动时扫描 + 下载完成后更新)
        self._local_index: dict[str, list[dict]] = {}
        self._wake = asyncio.Event()
        self._worker: asyncio.Task | None = None

    # ------------------------------------------------------------ 生命周期

    async def start(self) -> None:
        """启动 worker,并扫描磁盘重建本地缓存索引。"""
        self._local_index = await cache_store.scan_all()
        self._worker = asyncio.create_task(self._worker_loop())
        print(
            f"[download] 下载队列已启动,本地缓存 {len(self._local_index)} 首",
            flush=True,
        )

    async def stop(self) -> None:
        if self._worker:
            self._worker.cancel()
            try:
                await self._worker
            except asyncio.CancelledError:
                pass
            self._worker = None

    # ------------------------------------------------------------ 队列操作

    async def enqueue(self, track_ids: list[str], priority: bool = False) -> None:
        """批量入队。已完整缓存 / 已在队列中的跳过;priority=True 插入队首。

        缓存判定实时查磁盘(文件可能被外部删除,内存索引不可信);
        音频已缓存但视频缺失(failed 重试或升级旧缓存)时允许入队补下。
        """
        for tid in track_ids:
            local_audio = await cache_store.get_local_qualities(tid)
            state = self._states.get(tid, {}).get("state")
            if local_audio and state != "failed":
                # 视频曲目:本地缺视频 → 入队补下(兼容升级前只有音频的旧缓存);
                # 音频区曲目:有音频即完整
                if tid.startswith("bv"):
                    local_video = await cache_store.get_local_videos(tid)
                    if local_video:
                        self._mark_done(tid, local_audio)
                        continue
                    # 缺视频:落入下方入队逻辑
                else:
                    self._mark_done(tid, local_audio)
                    continue
            if state in ("pending", "downloading"):
                continue
            if priority:
                self._queue.appendleft(tid)
            else:
                self._queue.append(tid)
            self._states[tid] = {"state": "pending", "error": None}
        if track_ids:
            self._wake.set()

    def _mark_done(self, tid: str, local_audio: list[dict]) -> None:
        self._states[tid] = {"state": "done", "error": None}
        self._local_index[tid] = local_audio

    async def refresh_local(self, track_id: str) -> None:
        """删除缓存后同步本地索引与状态。"""
        quals = await cache_store.get_local_qualities(track_id)
        if quals:
            self._local_index[track_id] = quals
            self._states[track_id] = {"state": "done", "error": None}
        else:
            self._local_index.pop(track_id, None)
            if self._states.get(track_id, {}).get("state") in ("done", "failed"):
                self._states[track_id] = {"state": "none", "error": None}

    async def refresh_all(self) -> None:
        """清空缓存后全量重建索引。"""
        self._local_index = await cache_store.scan_all()

    async def prioritize(self, track_id: str) -> None:
        """点播优先:排队中的提到队首,failed 的重新排队。"""
        if track_id in self._queue:
            self._queue.remove(track_id)
            self._queue.appendleft(track_id)
            self._wake.set()
        elif self._states.get(track_id, {}).get("state") == "failed":
            self._states[track_id] = {"state": "pending", "error": None}
            self._queue.appendleft(track_id)
            self._wake.set()

    # ------------------------------------------------------------ 状态查询

    async def get_status(self, track_id: str) -> dict:
        """单曲缓存状态。音频/视频档位实时查磁盘,以文件真实存在为准。"""
        local = await cache_store.get_local_qualities(track_id)
        local_videos = await cache_store.get_local_videos(track_id)
        state = self._states.get(track_id, {}).get("state")
        # 队列状态(pending/downloading/failed)优先展示;否则按磁盘有无判断
        if state not in ("pending", "downloading", "failed"):
            state = "done" if local else "none"
        return {
            "track_id": track_id,
            "state": state,
            "error": self._states.get(track_id, {}).get("error"),
            "local_qualities": local,
            "local_videos": local_videos,
        }

    async def get_all_statuses(self) -> list[dict]:
        result = []
        for tid in self._all_known_ids():
            result.append(await self.get_status(tid))
        return result

    def _all_known_ids(self) -> set[str]:
        ids = set(self._local_index.keys())
        ids.update(self._states.keys())
        ids.update(self._queue)
        return ids

    # ------------------------------------------------------------ worker

    async def _worker_loop(self) -> None:
        while True:
            if not self._queue:
                self._wake.clear()
                await self._wake.wait()
                continue
            tid = self._queue.popleft()
            self._states[tid] = {"state": "downloading", "error": None}
            try:
                await self._download_track(tid)
                self._states[tid] = {"state": "done", "error": None}
                self._local_index[tid] = await cache_store.get_local_qualities(tid)
                print(f"[download] 完成: {tid}", flush=True)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self._states[tid] = {"state": "failed", "error": str(e)[:200]}
                print(f"[download] 失败: {tid} ({e})", flush=True)
            # 控频:任务间固定间隔
            await asyncio.sleep(TASK_INTERVAL)

    async def _download_track(self, track_id: str) -> None:
        """解析曲目,下载缺失的音频(最高档)/ 视频(最高画质)落盘。失败自动重试。

        音频与视频独立判断缺失:音频是核心(播放必需),视频是增强(MV 画面)。
        """
        last_err: Exception | None = None
        for attempt in range(RETRY_TIMES + 1):
            if attempt > 0:
                await asyncio.sleep(2)
            try:
                kind = "audio" if track_id.startswith("au") else "video"
                resolved = await resolve_track(kind, track_id)
                meta = {
                    "title": resolved.title,
                    "artist": resolved.artist,
                    "cover": resolved.cover,
                    "duration": resolved.duration,
                    "kind": resolved.kind,
                    "source": resolved.source,
                    "has_video": bool(resolved.video_streams),
                }
                audio_needed = not await cache_store.get_local_qualities(track_id)
                video_needed = bool(resolved.video_streams) and not (
                    await cache_store.get_local_videos(track_id)
                )
                if audio_needed:
                    await self._download_stream(
                        track_id, resolved.audio_streams[-1], meta, "audio"
                    )
                if video_needed:
                    # 同一曲目的两个请求之间也保持间隔,避免连续访问 CDN
                    await asyncio.sleep(TASK_INTERVAL)
                    await self._download_stream(
                        track_id, resolved.video_streams[-1], meta, "video"
                    )
                return
            except asyncio.CancelledError:
                raise
            except Exception as e:
                last_err = e
        raise last_err or RuntimeError("下载失败")

    async def _download_stream(self, track_id: str, stream, meta: dict, kind: str) -> None:
        """流式下载 CDN 媒体到临时文件,成功后改名入库。kind: audio / video。"""
        token = stream.stream_url.rsplit("/", 1)[-1]
        urls = get_stream_urls(token)
        if not urls:
            raise ValueError("无法获取流地址")
        tmp = cache_store.tmp_path(track_id, stream.quality_id, kind)
        tmp.parent.mkdir(parents=True, exist_ok=True)
        headers = {"User-Agent": BROWSER_UA, "Referer": REFERER}

        last_err: Exception | None = None
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10.0, read=None, write=None, pool=None),
            follow_redirects=True,
        ) as client:
            for url in urls:
                try:
                    with open(tmp, "wb") as f:
                        async with client.stream("GET", url, headers=headers) as resp:
                            if resp.status_code not in (200, 206):
                                last_err = RuntimeError(
                                    f"CDN 返回 {resp.status_code}"
                                )
                                continue
                            async for chunk in resp.aiter_bytes():
                                f.write(chunk)
                    # 下载成功:去掉 .part 后缀落位,再更新 meta
                    final = tmp.with_name(tmp.name.removesuffix(".part"))
                    os.replace(tmp, final)
                    await cache_store.save_downloaded(
                        track_id, stream.quality_id, meta, kind
                    )
                    return
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    last_err = e
        # 清理残留临时文件
        if tmp.exists():
            tmp.unlink(missing_ok=True)
        raise last_err or RuntimeError("所有 CDN 下载失败")


# 全局单例
manager = DownloadManager()
