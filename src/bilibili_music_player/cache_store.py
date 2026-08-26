"""本地音频缓存存储层。

目录结构:
  data/cache/{track_id}/q{quality_id}.m4a   音频文件
  data/cache/{track_id}/meta.json           元数据 + 已缓存档位
"""

import asyncio
import json
import time
from pathlib import Path

from .config import PROJECT_ROOT

CACHE_DIR = PROJECT_ROOT / "data" / "cache"

_lock = asyncio.Lock()

# 音质 id -> 标签(与 bilibili_client 的映射保持一致)
QUALITY_LABELS = {
    0: "标准",  # 音频区单档 / MP4 单文件
    30216: "64K",
    30232: "132K",
    30280: "192K",
    30251: "Hi-Res",
    30250: "杜比",
}

# 音质高低顺序(低 -> 高),用于「本地音质是否满足期望档」的判断
QUALITY_ORDER = [0, 30216, 30232, 30280, 30251, 30250]


def quality_label(quality_id: int) -> str:
    return QUALITY_LABELS.get(quality_id, str(quality_id))


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


def _file_path(track_id: str, quality_id: int) -> Path:
    return _track_dir(track_id) / f"q{quality_id}.m4a"


def _scan_local_qualities(track_id: str) -> list[dict]:
    """扫描磁盘上实际存在的音频文件(meta.json 可能滞后,以文件为准)。"""
    dir_path = _track_dir(track_id)
    if not dir_path.exists():
        return []
    result = []
    for f in sorted(dir_path.glob("q*.m4a")):
        try:
            quality_id = int(f.stem.removeprefix("q"))
        except ValueError:
            continue
        result.append(
            {
                "quality_id": quality_id,
                "quality": quality_label(quality_id),
                "file_size": f.stat().st_size,
            }
        )
    # 按音质从低到高排序(数值大小与音质高低不完全一致,需按顺序表)
    result.sort(
        key=lambda q: QUALITY_ORDER.index(q["quality_id"])
        if q["quality_id"] in QUALITY_ORDER
        else len(QUALITY_ORDER)
    )
    return result


# ---------------------------------------------------------------- 同步底层操作


def _save_file_sync(track_id: str, quality_id: int, meta: dict) -> Path:
    """保存音频文件 + 更新 meta(下载完成时调用)。"""
    dir_path = _track_dir(track_id)
    dir_path.mkdir(parents=True, exist_ok=True)
    old = _read_meta(track_id) or {}
    old.update(meta)
    old.setdefault("qualities", {})
    old["qualities"][str(quality_id)] = {
        "file": f"q{quality_id}.m4a",
        "downloaded_at": int(time.time()),
    }
    old["updated_at"] = int(time.time())
    _write_meta(track_id, old)
    return _file_path(track_id, quality_id)


def _delete_sync(track_id: str) -> None:
    """删除某曲目的全部本地缓存。"""
    import shutil

    shutil.rmtree(_track_dir(track_id), ignore_errors=True)


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


async def open_local_file(track_id: str, quality_id: int) -> Path | None:
    """返回本地音频文件路径(不存在返回 None)。"""
    async with _lock:
        path = _file_path(track_id, quality_id)

        def _check():
            return path if path.exists() else None

        return await asyncio.to_thread(_check)


async def save_downloaded(track_id: str, quality_id: int, meta: dict) -> Path:
    async with _lock:
        return await asyncio.to_thread(_save_file_sync, track_id, quality_id, meta)


async def delete_track(track_id: str) -> None:
    async with _lock:
        await asyncio.to_thread(_delete_sync, track_id)


async def clear_all() -> None:
    async with _lock:
        await asyncio.to_thread(_delete_all_sync)


def _delete_all_sync() -> None:
    import shutil

    shutil.rmtree(CACHE_DIR, ignore_errors=True)


async def cache_size() -> int:
    return await asyncio.to_thread(_cache_size_sync)


def tmp_path(track_id: str, quality_id: int) -> Path:
    """下载中的临时文件路径(下载完成后再改名入库)。"""
    return _track_dir(track_id) / f"q{quality_id}.m4a.part"
