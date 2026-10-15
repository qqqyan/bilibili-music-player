"""本地音频/视频缓存存储层。

目录结构:
  data/cache/{track_id}/q{quality_id}.m4a   音频文件
  data/cache/{track_id}/v{quality_id}.mp4   视频文件(MV 画面)
  data/cache/{track_id}/meta.json           元数据 + 已缓存档位
"""

import asyncio
import json
import time
from pathlib import Path

from ..config import PROJECT_ROOT

CACHE_DIR = PROJECT_ROOT / "data" / "cache"

_lock = asyncio.Lock()

from ..quality import (  # noqa: E402
    order_of,
    quality_label,
    video_quality_label,
)
def _track_dir(track_id: str) -> Path:
    # track_id 形如 bvBVxxx / au123,直接作目录名安全
    return CACHE_DIR / track_id


def _meta_path(track_id: str) -> Path:
    return _track_dir(track_id) / "meta.json"


def _read_meta(track_id: str) -> dict | None:
    path = _meta_path(track_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _write_meta(track_id: str, meta: dict) -> None:
    _track_dir(track_id).mkdir(parents=True, exist_ok=True)
    _meta_path(track_id).write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _audio_ext(track_id: str, quality_id: int) -> str:
    """音频文件扩展名:网易云(ne)按档位用 .flac/.mp3,其余 .m4a。"""
    if track_id.startswith("ne"):
        return ".flac" if quality_id >= 999000 else ".mp3"
    return ".m4a"


def _file_path(track_id: str, quality_id: int, kind: str = "audio") -> Path:
    if kind == "video":
        return _track_dir(track_id) / f"v{quality_id}.mp4"
    return _track_dir(track_id) / f"q{quality_id}{_audio_ext(track_id, quality_id)}"


def _scan_local_media(track_id: str, kind: str) -> list[dict]:
    """扫描磁盘上实际存在的媒体文件(meta.json 可能滞后,以文件为准)。"""
    dir_path = _track_dir(track_id)
    if not dir_path.exists():
        return []
    prefix = "v" if kind == "video" else "q"
    # 音频扩展名随来源变化(ne 曲 .mp3/.flac),扫描时遍历全部候选
    exts = [".mp4"] if kind == "video" else [".m4a", ".mp3", ".flac"]
    result = []
    for f in sorted(dir_path.glob(f"{prefix}*")):
        if f.suffix not in exts or not f.stem.removeprefix(prefix).isdigit():
            continue
        quality_id = int(f.stem.removeprefix(prefix))
        label = (
            video_quality_label(quality_id)
            if kind == "video"
            else quality_label(quality_id)
        )
        result.append(
            {
                "quality_id": quality_id,
                "quality": label,
                "file_size": f.stat().st_size,
            }
        )
    if kind == "audio":
        # 按音质从低到高排序(数值大小与音质高低不完全一致,需按顺序表)
        result.sort(key=lambda q: order_of(q["quality_id"], "audio"))
    else:
        # 视频画质枚举值恰与画质正相关,数值排序即可
        result.sort(key=lambda q: q["quality_id"])
    return result


def _scan_local_qualities(track_id: str) -> list[dict]:
    return _scan_local_media(track_id, "audio")


def _scan_local_videos(track_id: str) -> list[dict]:
    return _scan_local_media(track_id, "video")


# ---------------------------------------------------------------- 同步底层操作


def _save_file_sync(
    track_id: str, quality_id: int, meta: dict, kind: str = "audio", mime: str = ""
) -> Path:
    """保存媒体文件 + 更新 meta(下载完成时调用)。kind: audio / video。

    mime 记录进档位条目,本地播放时按它回放(旧缓存无 mime 按扩展名兜底)。
    """
    dir_path = _track_dir(track_id)
    dir_path.mkdir(parents=True, exist_ok=True)
    old = _read_meta(track_id) or {}
    old.update(meta)
    if kind == "video":
        old.setdefault("videos", {})
        old["videos"][str(quality_id)] = {
            "file": f"v{quality_id}.mp4",
            "downloaded_at": int(time.time()),
        }
    else:
        old.setdefault("qualities", {})
        old["qualities"][str(quality_id)] = {
            "file": f"q{quality_id}{_audio_ext(track_id, quality_id)}",
            "downloaded_at": int(time.time()),
        }
    if mime:
        (old["videos"] if kind == "video" else old["qualities"])[str(quality_id)]["mime"] = mime
    old["updated_at"] = int(time.time())
    _write_meta(track_id, old)
    return _file_path(track_id, quality_id, kind)


async def get_track_meta(track_id: str) -> dict | None:
    """曲目元数据缓存(下载时记录;供离线/未登录场景兜底)。"""
    async with _lock:
        return await asyncio.to_thread(_read_meta, track_id)


def _delete_sync(track_id: str) -> None:
    """删除某曲目的全部本地缓存。"""
    import shutil

    shutil.rmtree(_track_dir(track_id), ignore_errors=True)


def _cleanup_media_files(track_dir: Path, kind: str) -> list[tuple[Path, int]]:
    """只选完整媒体文件,兼容网易云与旧版缓存扩展名。"""
    prefix = "v" if kind == "video" else "q"
    extensions = {".mp4"} if kind == "video" else {".m4a", ".mp3", ".flac"}
    files = []
    for path in track_dir.glob(f"{prefix}*"):
        quality_id = path.stem.removeprefix(prefix)
        if path.is_file() and path.suffix in extensions and quality_id.isdigit():
            files.append((path, int(quality_id)))
    return files


def _cleanup_lower_sync(track_id: str, kind: str, keep_quality_id: int) -> None:
    """删除同类型更低档文件,档位顺序统一由 quality 模块提供。"""
    keep_order = order_of(keep_quality_id, kind)
    for path, quality_id in _cleanup_media_files(_track_dir(track_id), kind):
        if order_of(quality_id, kind) < keep_order:
            path.unlink(missing_ok=True)
            print(f"[cache] 清理旧档: {track_id} {kind} {quality_id}", flush=True)


def _cache_size_sync() -> int:
    """缓存目录总大小(字节)。"""
    if not CACHE_DIR.exists():
        return 0
    return sum(f.stat().st_size for f in CACHE_DIR.rglob("*") if f.is_file())


# ---------------------------------------------------------------- 异步接口


async def scan_all() -> dict[str, list[dict]]:
    """启动时扫描磁盘,重建「track_id -> 本地档位列表」索引。"""
    return await asyncio.to_thread(_scan_all_sync)


def _scan_all_sync() -> dict[str, list[dict]]:
    result = {}
    if not CACHE_DIR.exists():
        return result
    for meta_file in CACHE_DIR.glob("*/meta.json"):
        track_id = meta_file.parent.name
        quals = _scan_local_qualities(track_id)
        if quals:
            result[track_id] = quals
    return result


async def get_local_qualities(track_id: str) -> list[dict]:
    async with _lock:
        return await asyncio.to_thread(_scan_local_qualities, track_id)


async def get_local_videos(track_id: str) -> list[dict]:
    async with _lock:
        return await asyncio.to_thread(_scan_local_videos, track_id)


async def open_local_file(track_id: str, quality_id: int, kind: str = "audio") -> Path | None:
    """返回本地媒体文件路径(不存在返回 None)。kind: audio / video。

    优先用 meta.json 记录的真实文件名(扩展名随来源与版本变化,旧缓存
    可能是 .m4a,新规则可能是 .flac/.mp3),再按当前规则回退。
    """
    async with _lock:

        def _find():
            meta = _read_meta(track_id)
            if meta:
                record = (
                    (meta.get("videos") if kind == "video" else meta.get("qualities"))
                    or {}
                ).get(str(quality_id)) or {}
                name = record.get("file")
                if name:
                    p = _track_dir(track_id) / name
                    if p.exists():
                        return p
            p = _file_path(track_id, quality_id, kind)
            return p if p.exists() else None

        return await asyncio.to_thread(_find)


async def save_downloaded(
    track_id: str, quality_id: int, meta: dict, kind: str = "audio", mime: str = ""
) -> Path:
    async with _lock:
        return await asyncio.to_thread(
            _save_file_sync, track_id, quality_id, meta, kind, mime
        )


def _mime_from_suffix(path: Path, kind: str) -> str:
    if kind == "video":
        return "video/mp4"
    if path.suffix == ".mp3":
        return "audio/mpeg"
    if path.suffix == ".flac":
        return "audio/flac"
    return "audio/mp4"


async def get_local_mime(track_id: str, quality_id: int, kind: str = "audio") -> str:
    """本地文件的回放 mime:优先 meta 记录的下载时 mime,按扩展名兜底。"""
    async with _lock:

        def _find():
            meta = _read_meta(track_id)
            if meta:
                record = (
                    (meta.get("videos") if kind == "video" else meta.get("qualities"))
                    or {}
                ).get(str(quality_id)) or {}
                if record.get("mime"):
                    return record["mime"]
                name = record.get("file")
                if name:
                    return _mime_from_suffix(_track_dir(track_id) / name, kind)
            return _mime_from_suffix(_file_path(track_id, quality_id, kind), kind)

        return await asyncio.to_thread(_find)


async def delete_track(track_id: str) -> None:
    async with _lock:
        await asyncio.to_thread(_delete_sync, track_id)


async def cleanup_lower(track_id: str, kind: str, keep_quality_id: int) -> None:
    """删除同类型更低档本地文件(设置开启「自动清理旧档」时由下载器调用)。"""
    async with _lock:
        await asyncio.to_thread(_cleanup_lower_sync, track_id, kind, keep_quality_id)


def _cleanup_all_sync() -> int:
    """遍历全部缓存,每首曲目音频/视频各只保留最高档。返回删除文件数。"""
    removed = 0
    if not CACHE_DIR.exists():
        return 0
    for track_dir in CACHE_DIR.iterdir():
        if not track_dir.is_dir():
            continue
        for kind in ("audio", "video"):
            files = _cleanup_media_files(track_dir, kind)
            if len(files) <= 1:
                continue
            files.sort(key=lambda item: order_of(item[1], kind))
            for path, _ in files[:-1]:  # 只保留最高档
                path.unlink(missing_ok=True)
                removed += 1
                print(f"[cache] 清理旧档: {track_dir.name} {kind} {path.stem}", flush=True)
    return removed


async def cleanup_all() -> int:
    """遍历全部缓存只保留每首最高档(设置开启「清理旧档」时立即执行)。"""
    async with _lock:
        return await asyncio.to_thread(_cleanup_all_sync)


async def clear_all() -> None:
    async with _lock:
        await asyncio.to_thread(_delete_all_sync)


def _delete_all_sync() -> None:
    import shutil

    shutil.rmtree(CACHE_DIR, ignore_errors=True)


async def cache_size() -> int:
    return await asyncio.to_thread(_cache_size_sync)


def tmp_path(track_id: str, quality_id: int, kind: str = "audio") -> Path:
    """下载中的临时文件路径(下载完成后再改名入库)。kind: audio / video。"""
    return _file_path(track_id, quality_id, kind).with_suffix(
        ".m4a.part" if kind == "audio" else ".mp4.part"
    )
