"""歌单持久化:项目目录下的 JSON 文件(data/playlist.json)。

跟随项目走,换浏览器/清浏览器数据不丢;为后续多端共享打底。
"""

import asyncio
import json
from pathlib import Path

from ..config import PROJECT_ROOT

DATA_DIR = PROJECT_ROOT / "data"
PLAYLIST_FILE = DATA_DIR / "playlist.json"

_lock = asyncio.Lock()


def _read() -> list[dict]:
    if not PLAYLIST_FILE.exists():
        return []
    try:
        return json.loads(PLAYLIST_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []  # 文件损坏时按空歌单处理


def _write(items: list[dict]) -> None:
    # 原子写(.tmp + replace):进程被强杀在写入中途也不会损坏歌单
    import os

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = PLAYLIST_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, PLAYLIST_FILE)


async def get_playlist() -> list[dict]:
    async with _lock:
        return await asyncio.to_thread(_read)


async def save_playlist(items: list[dict]) -> None:
    async with _lock:
        await asyncio.to_thread(_write, items)
