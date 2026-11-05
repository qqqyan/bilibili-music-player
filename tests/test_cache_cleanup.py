"""缓存清理覆盖各平台音频扩展名,只操作临时目录中的文件。"""

import asyncio

import pytest

from bilibili_music_player.repositories import cache_store


@pytest.fixture()
def cache_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(cache_store, "CACHE_DIR", tmp_path)
    return tmp_path


def make_files(cache_dir, track_id, names):
    directory = cache_dir / track_id
    directory.mkdir()
    for name in names:
        (directory / name).write_bytes(b"test")
    return directory


@pytest.mark.parametrize("highest", ["q320000.mp3", "q999000.flac"])
def test_cleanup_all_netease_keeps_highest_across_extensions(cache_dir, highest):
    directory = make_files(cache_dir, "ne1", ["q128000.mp3", "q192000.m4a", highest])
    assert asyncio.run(cache_store.cleanup_all()) == 2
    assert {p.name for p in directory.iterdir()} == {highest}


def test_cleanup_lower_netease_preserves_higher_and_other_files(cache_dir):
    directory = make_files(cache_dir, "ne1", [
        "q128000.mp3", "q192000.m4a", "q320000.mp3", "q999000.flac",
        "v80.mp4", "meta.json", "q128000.mp3.part", "qnotes.mp3",
    ])
    asyncio.run(cache_store.cleanup_lower("ne1", "audio", 320000))
    assert {p.name for p in directory.iterdir()} == {
        "q320000.mp3", "q999000.flac", "v80.mp4", "meta.json",
        "q128000.mp3.part", "qnotes.mp3",
    }


@pytest.mark.parametrize("operation", ["all", "lower"])
def test_cleanup_preserves_bilibili_quality_order_and_video(cache_dir, operation):
    directory = make_files(cache_dir, "bvTEST", [
        "q30280.m4a", "q30251.m4a", "q30250.m4a", "v32.mp4", "v80.mp4",
        "meta.json", "q30216.m4a.part", "qnotes.m4a", "vnotes.mp4",
    ])
    if operation == "all":
        assert asyncio.run(cache_store.cleanup_all()) == 3
    else:
        asyncio.run(cache_store.cleanup_lower("bvTEST", "audio", 30250))
        asyncio.run(cache_store.cleanup_lower("bvTEST", "video", 80))
    assert {p.name for p in directory.iterdir()} == {
        "q30250.m4a", "v80.mp4", "meta.json", "q30216.m4a.part",
        "qnotes.m4a", "vnotes.mp4",
    }


def test_cleanup_missing_cache_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(cache_store, "CACHE_DIR", tmp_path / "missing")
    assert asyncio.run(cache_store.cleanup_all()) == 0
    asyncio.run(cache_store.cleanup_lower("ne1", "audio", 999000))


def test_cleanup_all_legacy_netease_uses_quality_order(cache_dir):
    directory = make_files(cache_dir, "ne1", [
        "q999000.m4a", "q320000.m4a", "q128000.m4a", "q192000.m4a",
    ])
    assert asyncio.run(cache_store.cleanup_all()) == 3
    assert {p.name for p in directory.iterdir()} == {"q999000.m4a"}


def test_cleanup_all_ignores_media_named_directories(cache_dir):
    directory = make_files(cache_dir, "ne1", ["q128000.mp3", "q320000.mp3"])
    (directory / "q192000.mp3").mkdir()
    assert asyncio.run(cache_store.cleanup_all()) == 1
    assert (directory / "q192000.mp3").is_dir()
    assert (directory / "q320000.mp3").exists()


def test_cleanup_api_reports_removed_files(test_app, cache_dir):
    from fastapi.testclient import TestClient

    directory = make_files(cache_dir, "ne1", ["q128000.mp3", "q999000.flac"])
    with TestClient(test_app) as client:
        response = client.post("/api/cache/cleanup")
    assert response.status_code == 200
    assert response.json() == {"removed": 1}
    assert {p.name for p in directory.iterdir()} == {"q999000.flac"}
