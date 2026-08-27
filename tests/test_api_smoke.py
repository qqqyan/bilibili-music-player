"""API 冒烟测试:路由挂载与无网络接口的正确性。

依赖网络的接口(搜索/解析/播放)不在单测范围——由手动冒烟脚本覆盖。
重构后的分层(import 链、路由注册)由本文件兜底。
"""

import pytest
from fastapi.testclient import TestClient

from bilibili_music_player.repositories import playlist_store, settings_store


def test_health(test_app):
    with TestClient(test_app) as client:
        resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_qualities(test_app):
    """档位列表接口:结构正确(无网络依赖)。"""
    with TestClient(test_app) as client:
        resp = client.get("/api/qualities")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["audio"]) >= 5  # 64K/132K/192K/Hi-Res/杜比
    assert len(data["video"]) >= 5
    # 每个档位都有 id 与 label
    for q in data["audio"] + data["video"]:
        assert "id" in q and "label" in q


def test_settings_roundtrip(test_app, tmp_path, monkeypatch):
    """设置读写走隔离的临时文件,不碰真实数据。"""
    monkeypatch.setattr(settings_store, "SETTINGS_FILE", tmp_path / "settings.json")
    with TestClient(test_app) as client:
        resp = client.get("/api/settings")
    assert resp.status_code == 200
    defaults = resp.json()
    assert defaults["cleanup_old_quality"] is False

    with TestClient(test_app) as client:
        resp = client.put("/api/settings", json={"cleanup_old_quality": True})
    assert resp.status_code == 200
    assert resp.json()["cleanup_old_quality"] is True

    # 持久化生效:重新读
    assert settings_store.load_settings()["cleanup_old_quality"] is True


def test_playlist_roundtrip(test_app, tmp_path, monkeypatch):
    """歌单读写走隔离的临时文件。"""
    monkeypatch.setattr(playlist_store, "PLAYLIST_FILE", tmp_path / "playlist.json")
    track = {
        "id": "bvTEST0001",
        "title": "测试曲目",
        "artist": "测试 UP",
        "cover": "https://example.com/x.jpg",
        "duration": 100,
        "source": "bilibili 视频",
    }
    with TestClient(test_app) as client:
        resp = client.put("/api/playlist", json=[track])
    assert resp.status_code == 200
    assert len(resp.json()) == 1

    with TestClient(test_app) as client:
        resp = client.get("/api/playlist")
    assert resp.status_code == 200
    assert resp.json()[0]["id"] == "bvTEST0001"


@pytest.mark.parametrize(
    "path",
    [
        "/api/qualities",
        "/api/playlist",
        "/api/settings",
        "/api/health",
    ],
)
def test_routes_registered(test_app, path):
    """无网络路由可访问(网络路由的注册正确性由 conftest 组装 + 手动冒烟覆盖)。"""
    with TestClient(test_app) as client:
        resp = client.get(path)
    assert resp.status_code == 200, f"路由不可用: {path}"
