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

from ..repositories import cache_store
from .parse_service import resolve_track
from .. import quality
from ..quality import pick_stream_by_quality
from .stream_proxy import BROWSER_UA, REFERER, get_stream_urls

# 下载任务之间的固定间隔(秒),避免连续请求触发风控
TASK_INTERVAL = 1.5
# 下载并发数(CDN 流下载,2 并发对风控影响小;API 解析另有限频)
DOWNLOAD_CONCURRENCY = 2
# 失败重试次数(不含首次)
RETRY_TIMES = 1


class DownloadManager:
    def __init__(self) -> None:
        # 队列元素: {"track_id", "desired_audio", "desired_video"}
        self._queue: deque[dict] = deque()
        # 已检查待下载的任务(阶段 2 使用,支持点播重排)
        self._to_download: list[dict] = []
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

    async def enqueue(
        self,
        track_ids: list[str],
        priority: bool = False,
        force: bool = False,
        desired_audio: int = -1,
        desired_video: int = -1,
    ) -> None:
        """批量入队。已完整缓存 / 已在队列中的跳过;priority=True 插入队首。

        force=True 时跳过缓存检查强制入队,worker 会解析远程档位,
        按期望档(不存在则降级)只补下缺失的档。
        """
        for tid in track_ids:
            # 点播优先:已入队(检查中/待下载/失败)的曲目也要提队首
            if priority and self._try_prioritize(tid):
                continue
            if not force:
                local_audio = await cache_store.get_local_qualities(tid)
                state = self._states.get(tid, {}).get("state")
                if local_audio and state != "failed":
                    # 本地缺视频 → 入队补下(兼容升级前只有音频的旧缓存)
                    local_video = await cache_store.get_local_videos(tid)
                    if local_video:
                        self._mark_done(tid, local_audio)
                        continue
                    # 缺视频:落入下方入队逻辑
            state = self._states.get(tid, {}).get("state")
            # 检查中/待下载/下载中的不重复入队(防并发下载两遍)
            if state in ("checking", "pending", "downloading"):
                continue
            item = {
                "track_id": tid,
                "desired_audio": desired_audio,
                "desired_video": desired_video,
            }
            if priority:
                self._queue.appendleft(item)
            else:
                self._queue.append(item)
            # 入队即「检查中」:worker 检查后转为待下载/下载中/完成
            self._states[tid] = {"state": "checking", "error": None}
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

    def _try_prioritize(self, track_id: str) -> bool:
        """把已在队列/待下载/failed 的曲目提到最前,返回是否已处理。

        未入队(或正在下载/检查)返回 False/True 语义见各分支。
        """
        # 1) 已检查待下载列表:移到最前
        item = next(
            (i for i in self._to_download if i["track_id"] == track_id), None
        )
        if item is not None:
            self._to_download.remove(item)
            self._to_download.insert(0, item)
            return True
        # 2) 未检查队列:移到队首
        item = next((i for i in self._queue if i["track_id"] == track_id), None)
        if item is not None:
            self._queue.remove(item)
            self._queue.appendleft(item)
            self._wake.set()
            return True
        # 3) failed:重新入队检查
        if self._states.get(track_id, {}).get("state") == "failed":
            self._states[track_id] = {"state": "checking", "error": None}
            self._queue.appendleft(
                {"track_id": track_id, "desired_audio": -1, "desired_video": -1}
            )
            self._wake.set()
            return True
        # 4) 下载中/检查中:视为已处理(正在处理,不会重复下载)
        if self._states.get(track_id, {}).get("state") in ("checking", "downloading"):
            return True
        # 5) 未入队:交回 enqueue 走正常入队
        return False

    async def prioritize(self, track_id: str) -> None:
        """点播优先:排队中的提到最前,failed 的重新排队。"""
        self._try_prioritize(track_id)

    # ------------------------------------------------------------ 状态查询

    async def get_status(self, track_id: str) -> dict:
        """单曲缓存状态。音频/视频档位实时查磁盘,以文件真实存在为准。"""
        local = await cache_store.get_local_qualities(track_id)
        local_videos = await cache_store.get_local_videos(track_id)
        state = self._states.get(track_id, {}).get("state")
        # 队列状态(checking/pending/downloading/failed)优先展示;否则按磁盘有无判断
        if state not in ("checking", "pending", "downloading", "failed"):
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
        # 队列元素是 dict,需提取 track_id
        ids.update(item["track_id"] for item in self._queue)
        return ids

    # ------------------------------------------------------------ worker

    async def _worker_loop(self) -> None:
        # 任务池模式:固定并发槽,槽位一空立即启动下一个。
        # 点播任务经 prioritize 插到 _to_download 最前,下一个空槽先轮到它,
        # 不必等当前批次整体完成。
        pending: set[asyncio.Task] = set()
        while True:
            # 1. 处理新入队(检查后插到待下载列表最前,点播优先)
            if self._queue:
                new_items = list(self._queue)
                self._queue.clear()
                new_tasks = await self._check_all(new_items)
                self._to_download = new_tasks + self._to_download
            # 2. 填充空闲槽位
            while len(pending) < DOWNLOAD_CONCURRENCY and self._to_download:
                task = self._to_download.pop(0)
                pending.add(asyncio.create_task(self._download_one(task)))
            # 3. 等待:有下载任务则等到任一完成(期间新入队可插队),
            #    无任务则休眠等唤醒
            if pending:
                if self._queue or self._to_download:
                    done, pending = await asyncio.wait(
                        pending, return_when=asyncio.FIRST_COMPLETED
                    )
                else:
                    await asyncio.gather(*pending)
                    pending = set()
                continue
            if not self._queue:
                self._wake.clear()
                await self._wake.wait()

    async def _download_one(self, task: dict) -> None:
        """下载单个任务(阶段 2 并发单元)。"""
        tid = task["track_id"]
        self._states[tid] = {"state": "downloading", "error": None}
        try:
            await self._download_parts(tid, task)
            self._states[tid] = {"state": "done", "error": None}
            self._local_index[tid] = await cache_store.get_local_qualities(tid)
            print(f"[download] 完成: {tid}", flush=True)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            self._states[tid] = {"state": "failed", "error": str(e)[:200]}
            print(f"[download] 失败: {tid} ({e})", flush=True)
        # 控频:任务完成后固定间隔(并发批内并行计时,批间由循环衔接)
        await asyncio.sleep(TASK_INTERVAL)

    async def _check_all(self, items: list[dict]) -> list[dict]:
        """并发检查一批曲目(解析+期望档判断),返回需要下载的任务列表。

        解析并发由 bilibili_client 的信号量(Semaphore(2))天然限频。
        检查偶发失败自动重试一次(zoku 并发解析偶有竞态)。
        """
        to_download: list[dict] = []

        async def check_one(item: dict):
            tid = item["track_id"]
            self._states[tid] = {"state": "checking", "error": None}
            for attempt in range(2):
                try:
                    task = await self._check_track(tid, item)
                    if task is None:
                        self._states[tid] = {"state": "done", "error": None}
                        self._local_index[tid] = (
                            await cache_store.get_local_qualities(tid)
                        )
                    else:
                        self._states[tid] = {"state": "pending", "error": None}
                        to_download.append(task)
                    return
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    if attempt == 0:
                        await asyncio.sleep(1.0)  # 偶发竞态,重试一次
                        continue
                    import traceback

                    traceback.print_exc()
                    self._states[tid] = {"state": "failed", "error": str(e)[:200]}
                    print(f"[download] 检查失败: {tid} ({e})", flush=True)

        await asyncio.gather(*(check_one(item) for item in items))
        return to_download

    async def _check_track(self, track_id: str, item: dict) -> dict | None:
        """阶段 1:解析曲目并按期望档判断是否需要下载。

        需要下载返回任务 dict,否则 None。
        """
        resolved = await resolve_track(track_id)
        meta = {
            "title": resolved.title,
            "artist": resolved.artist,
            "cover": resolved.cover,
            "duration": resolved.duration,
            "source": resolved.source,
            "has_video": bool(resolved.video_streams),
        }
        local_audio = await cache_store.get_local_qualities(track_id)
        local_video = await cache_store.get_local_videos(track_id)
        audio_stream = _pick_desired_stream(
            resolved.audio_streams, item["desired_audio"], "audio"
        )
        video_stream = _pick_desired_stream(
            resolved.video_streams, item["desired_video"], "video"
        )
        audio_needed = audio_stream is not None and not _local_satisfies(
            local_audio, audio_stream, "audio"
        )
        video_needed = video_stream is not None and not _local_satisfies(
            local_video, video_stream, "video"
        )
        if not audio_needed and not video_needed:
            return None
        return {
            "track_id": track_id,
            "audio_stream": audio_stream if audio_needed else None,
            "video_stream": video_stream if video_needed else None,
            "meta": meta,
        }

    async def _download_parts(self, track_id: str, task: dict) -> None:
        """阶段 2:下载任务中的音频/视频部分(失败自动重试)。"""
        last_err: Exception | None = None
        for attempt in range(RETRY_TIMES + 1):
            if attempt > 0:
                await asyncio.sleep(2)
            try:
                if task["audio_stream"] is not None:
                    await self._download_stream(
                        track_id, task["audio_stream"], task["meta"], "audio"
                    )
                    await self._maybe_cleanup_lower(
                        track_id, "audio", task["audio_stream"].quality_id
                    )
                if task["video_stream"] is not None:
                    # 同一曲目的两个请求之间也保持间隔,避免连续访问 CDN
                    await asyncio.sleep(TASK_INTERVAL)
                    await self._download_stream(
                        track_id, task["video_stream"], task["meta"], "video"
                    )
                    await self._maybe_cleanup_lower(
                        track_id, "video", task["video_stream"].quality_id
                    )
                return
            except asyncio.CancelledError:
                raise
            except Exception as e:
                last_err = e
        raise last_err or RuntimeError("下载失败")

    async def _download_track(self, track_id: str, desired_audio: int, desired_video: int) -> None:
        """解析曲目,按期望档(不存在则降级到其最好档)补下缺失的音频/视频。失败自动重试。"""
        last_err: Exception | None = None
        for attempt in range(RETRY_TIMES + 1):
            if attempt > 0:
                await asyncio.sleep(2)
            try:
                resolved = await resolve_track(track_id)
                meta = {
                    "title": resolved.title,
                    "artist": resolved.artist,
                    "cover": resolved.cover,
                    "duration": resolved.duration,
                    "source": resolved.source,
                    "has_video": bool(resolved.video_streams),
                }
                local_audio = await cache_store.get_local_qualities(track_id)
                local_video = await cache_store.get_local_videos(track_id)
                audio_stream = _pick_desired_stream(
                    resolved.audio_streams, desired_audio, "audio"
                )
                video_stream = _pick_desired_stream(
                    resolved.video_streams, desired_video, "video"
                )
                # 本地最高档已满足期望档(>= 期望)则不下载:选了低档时
                # 即使本地没有精确档,有更高档也算满足,不降级重下
                audio_needed = audio_stream is not None and not _local_satisfies(
                    local_audio, audio_stream, "audio"
                )
                video_needed = video_stream is not None and not _local_satisfies(
                    local_video, video_stream, "video"
                )
                if audio_needed:
                    await self._download_stream(track_id, audio_stream, meta, "audio")
                    await self._maybe_cleanup_lower(track_id, "audio", audio_stream.quality_id)
                if video_needed:
                    # 同一曲目的两个请求之间也保持间隔,避免连续访问 CDN
                    await asyncio.sleep(TASK_INTERVAL)
                    await self._download_stream(track_id, video_stream, meta, "video")
                    await self._maybe_cleanup_lower(track_id, "video", video_stream.quality_id)
                return
            except asyncio.CancelledError:
                raise
            except Exception as e:
                last_err = e
        raise last_err or RuntimeError("下载失败")

    async def _maybe_cleanup_lower(self, track_id: str, kind: str, quality_id: int) -> None:
        """设置开启「自动清理旧档」时,删除刚下载档位以下的旧缓存。"""
        from ..repositories import settings_store

        if settings_store.load_settings().get("cleanup_old_quality"):
            await cache_store.cleanup_lower(track_id, kind, quality_id)

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


def _local_satisfies(local_quals: list[dict], want_stream, kind: str) -> bool:
    """本地最高档是否已满足期望档(本地最高 >= 期望)。

    音质按顺序表比较,视频按数值比较。
    """
    if not local_quals:
        return False
    if kind == "video":
        return max(q["quality_id"] for q in local_quals) >= want_stream.quality_id
    order = quality.QUALITY_ORDER
    local_best = max(
        order.index(q["quality_id"]) if q["quality_id"] in order else len(order)
        for q in local_quals
    )
    want = (
        order.index(want_stream.quality_id)
        if want_stream.quality_id in order
        else len(order)
    )
    return local_best >= want


def _pick_desired_stream(streams: list, desired_id: int, kind: str):
    """期望档选择(下载用)。desired_id: -1=最高;-2=跳过该类型。"""
    if desired_id == -2:
        return None
    return pick_stream_by_quality(streams, desired_id, kind)


# 全局单例
manager = DownloadManager()
