"""缓存路径边界回归;仅在 tmp_path 内创建、读取和删除测试数据。"""

import asyncio

import pytest
from fastapi.testclient import TestClient

from bilibili_music_player.app import app
from bilibili_music_player.repositories import cache_store
from bilibili_music_player.services.download_manager import DownloadManager


@pytest.fixture
def isolated_cache(tmp_path, monkeypatch):
    cache = tmp_path / "data" / "cache"
    cache.mkdir(parents=True)
    sentinel = cache.parent / "playlist.json"
    sentinel.write_text("keep playlist", encoding="utf-8")
    monkeypatch.setattr(cache_store, "CACHE_DIR", cache)
    return cache, sentinel


BAD_IDS = [
    "", ".", "..", "../outside", "bv123/../../outside", "/tmp/outside",
    r"..\outside", r"C:\outside", "C:outside", r"\\server\share",
    "bv123.", "bv123 ", "bv123:stream", "CON", "nul", "COM1", "LPT9",
    "bv123\x00", "%2e%2e", "%252e%252e",
]


@pytest.mark.parametrize("track_id", BAD_IDS)
def test_reject_unsafe_ids_for_all_cache_paths(isolated_cache, track_id):
    cache, sentinel = isolated_cache
    operations = [
        lambda: cache_store._delete_sync(track_id),
        lambda: cache_store._read_meta(track_id),
        lambda: cache_store._write_meta(track_id, {}),
        lambda: cache_store._scan_local_qualities(track_id),
        lambda: cache_store._scan_local_videos(track_id),
        lambda: cache_store._save_file_sync(track_id, 30280, {}),
        lambda: cache_store._cleanup_lower_sync(track_id, "audio", 30280),
        lambda: cache_store.tmp_path(track_id, 30280),
        lambda: asyncio.run(cache_store.open_local_file(track_id, 30280)),
    ]
    for operation in operations:
        with pytest.raises(cache_store.InvalidCachePath):
            operation()
        assert sentinel.read_text() == "keep playlist"
        assert cache.is_dir()


@pytest.mark.parametrize("track_id", ["bvBV1xx411c7mD", "au123", "ne123", "legacy-track_1"])
def test_valid_ids_still_save_play_and_delete(isolated_cache, track_id):
    cache, sentinel = isolated_cache
    path = cache_store._save_file_sync(track_id, 30280, {"title": "test"})
    path.write_bytes(b"media")
    assert asyncio.run(cache_store.open_local_file(track_id, 30280)) == path
    assert cache_store._scan_local_qualities(track_id)[0]["quality_id"] == 30280
    cache_store._delete_sync(track_id)
    assert not (cache / track_id).exists()
    assert sentinel.read_text() == "keep playlist"


@pytest.mark.parametrize("encoded_id", ["%2E", "%2E%2E", "..%5Coutside", "C%3Aoutside", "CON", "%252E%252E", "%00"])
@pytest.mark.parametrize("route", ["delete", "status", "audio", "video"])
def test_api_rejects_encoded_paths_with_400(isolated_cache, encoded_id, route):
    cache, sentinel = isolated_cache
    # No lifespan: no network initialization or background workers.
    client = TestClient(app)
    if route == "delete":
        response = client.delete(f"/api/cache/{encoded_id}")
    elif route == "status":
        response = client.get(f"/api/cache/status/{encoded_id}")
    else:
        suffix = "/video" if route == "video" else ""
        response = client.get(f"/api/local/{encoded_id}{suffix}?quality_id=30280")
    assert response.status_code == 400
    assert sentinel.read_text() == "keep playlist"
    assert cache.is_dir()


@pytest.mark.parametrize("force", [False, True])
def test_queue_rejects_entire_invalid_batch(isolated_cache, force):
    manager = DownloadManager()
    with pytest.raises(cache_store.InvalidCachePath):
        asyncio.run(manager.enqueue(["bvValid", ".."], force=force))
    assert not manager._queue
    assert not manager._states
    response = TestClient(app).post("/api/cache/queue", json={"track_ids": [".."], "force": force})
    assert response.status_code == 400


def test_track_symlink_cannot_escape_or_break_bulk_operations(isolated_cache, tmp_path):
    cache, sentinel = isolated_cache
    outside = tmp_path / "outside"
    outside.mkdir()
    for name in ["meta.json", "q30216.m4a", "q30280.m4a"]:
        (outside / name).write_text("keep outside")
    (cache / "bvLinked").symlink_to(outside, target_is_directory=True)
    for operation in [
        lambda: cache_store._delete_sync("bvLinked"),
        lambda: cache_store._read_meta("bvLinked"),
        lambda: cache_store._save_file_sync("bvLinked", 30280, {}),
        lambda: cache_store._cleanup_lower_sync("bvLinked", "audio", 30280),
        lambda: cache_store.tmp_path("bvLinked", 30280),
    ]:
        with pytest.raises(cache_store.InvalidCachePath):
            operation()
    assert cache_store._scan_all_sync() == {}
    assert cache_store._cleanup_all_sync() == 0
    assert all(p.read_text() == "keep outside" for p in outside.iterdir())
    assert sentinel.read_text() == "keep playlist"


@pytest.mark.parametrize("name", ["../playlist.json", "/tmp/outside", r"..\outside", "C:outside"])
def test_metadata_cannot_select_outside_file(isolated_cache, name):
    cache_store._write_meta("ne123", {"qualities": {"30280": {"file": name}}})
    with pytest.raises(cache_store.InvalidCachePath):
        asyncio.run(cache_store.open_local_file("ne123", 30280))


@pytest.mark.parametrize("name", ["meta.json", "q30280.m4a", "q30280.m4a.part"])
def test_file_symlinks_are_rejected(isolated_cache, name):
    cache, sentinel = isolated_cache
    track = cache / "bv123"
    track.mkdir()
    (track / name).symlink_to(sentinel)
    operation = {
        "meta.json": lambda: cache_store._write_meta("bv123", {}),
        "q30280.m4a": lambda: asyncio.run(cache_store.open_local_file("bv123", 30280)),
        "q30280.m4a.part": lambda: cache_store.tmp_path("bv123", 30280),
    }[name]
    with pytest.raises(cache_store.InvalidCachePath):
        operation()
    assert sentinel.read_text() == "keep playlist"


@pytest.mark.parametrize("encoded_id", ["..%2Foutside", "%2Ftmp%2Foutside"])
def test_encoded_slashes_do_not_match_delete_route(isolated_cache, encoded_id):
    cache, sentinel = isolated_cache
    response = TestClient(app).delete(f"/api/cache/{encoded_id}")
    assert response.status_code == 404
    assert cache.is_dir()
    assert sentinel.read_text() == "keep playlist"


def test_valid_delete_api_only_removes_selected_track(isolated_cache, monkeypatch):
    from unittest.mock import AsyncMock
    from bilibili_music_player.routers.cache import download_manager

    cache, sentinel = isolated_cache
    selected = cache_store._save_file_sync("bv123", 30280, {})
    selected.write_bytes(b"delete")
    other = cache_store._save_file_sync("ne123", 320000, {})
    other.write_bytes(b"keep")
    refresh = AsyncMock()
    monkeypatch.setattr(download_manager, "refresh_local", refresh)
    response = TestClient(app).delete("/api/cache/bv123")
    assert response.status_code == 200
    assert response.json() == {"deleted": "bv123"}
    refresh.assert_awaited_once_with("bv123")
    assert not selected.parent.exists()
    assert other.read_bytes() == b"keep"
    assert sentinel.read_text() == "keep playlist"
