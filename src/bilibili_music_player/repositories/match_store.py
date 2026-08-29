"""歌单匹配任务持久化:data/match_job.json(单任务,重复导入覆盖)。

与 playlist_store 同模式(锁 + 线程读写),区别:
    - 任务文件较大(几百首 × 候选),整文件原子写(.tmp + os.replace),
      防止写入中途崩溃产生撕裂文件丢整个任务
    - 文件损坏按「无任务」处理(重新导入覆盖;只丢匹配进度,不丢歌单)
"""

import asyncio
import json
import os

from ..config import PROJECT_ROOT

DATA_DIR = PROJECT_ROOT / "data"
MATCH_FILE = DATA_DIR / "match_job.json"

_lock = asyncio.Lock()


def _read() -> dict | None:
    if not MATCH_FILE.exists():
        return None
    try:
        data = json.loads(MATCH_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, OSError):
        return None


def _write(job: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = MATCH_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, MATCH_FILE)


async def load_job() -> dict | None:
    async with _lock:
        return await asyncio.to_thread(_read)


async def save_job(job: dict) -> None:
    async with _lock:
        await asyncio.to_thread(_write, job)


async def clear_job() -> None:
    async with _lock:
        def _unlink() -> None:
            MATCH_FILE.unlink(missing_ok=True)

        await asyncio.to_thread(_unlink)
