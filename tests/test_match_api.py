"""歌单匹配 API 冒烟测试:导入/查询/选择/入列(无网络,数据文件隔离)。"""

import json

from fastapi.testclient import TestClient

from bilibili_music_player.repositories import match_store, playlist_store, settings_store
from bilibili_music_player.services import match_service
from bilibili_music_player.services.match_service import manager

NETEASE_JSON = json.dumps([
    {"id": 1, "name": "不完全花", "ar": [{"name": "kotoha"}], "dt": 220000, "tns": [], "alia": []},
    {"id": 2, "name": "心音", "ar": [{"name": "洛天依Official"}], "dt": 201000, "tns": [], "alia": []},
])

SEEDED_JSONL = "\n".join([
    '{"netease_id": 3, "name": "夏恋慕", "artists": ["kobasolo", "春茶"], "duration_ms": 200000,'
    ' "status": "matched", "chosen": {"bvid": "BVTESTAA1", "title": "夏恋慕", "up": "kobasolo",'
    ' "mid": 1, "cover": "", "duration_s": 200, "play": 10, "score": 90},'
    ' "candidates": [{"bvid": "BVTESTAA1", "title": "夏恋慕", "up": "kobasolo", "mid": 1,'
    ' "cover": "", "duration_s": 200, "play": 10, "score": 90}]}',
])


def _isolated(tmp_path, monkeypatch):
    """隔离单例状态与数据文件。"""
    manager._job = None
    manager._pause_requested = False
    monkeypatch.setattr(match_store, "MATCH_FILE", tmp_path / "match_job.json")
    monkeypatch.setattr(playlist_store, "PLAYLIST_FILE", tmp_path / "playlist.json")
    monkeypatch.setattr(settings_store, "SETTINGS_FILE", tmp_path / "settings.json")


def test_no_job_404(test_app):
    manager._job = None
    with TestClient(test_app) as client:
        resp = client.get("/api/match/job")
    assert resp.status_code == 404


def test_import_netease_and_summary(test_app, tmp_path, monkeypatch):
    _isolated(tmp_path, monkeypatch)
    with TestClient(test_app) as client:
        # 先写入歌手映射,导入时应生成映射查询词
        client.put("/api/settings", json={
            "artist_map": [
                {"singer": "kotoha", "netease": ["kotoha"], "bilibili": ["MARUMOCHI_LABEL"]}
            ]
        })
        resp = client.post(
            "/api/match/import",
            json={"name": "我的歌单", "content": NETEASE_JSON},
        )
        assert resp.status_code == 200
        summary = resp.json()
        assert summary["total"] == 2 and summary["status"] == "idle"

        resp = client.get("/api/match/job", params={"summary": "true"})
        assert resp.status_code == 200 and resp.json()["total"] == 2

        resp = client.get("/api/match/job")
        job = resp.json()
        assert job["source_platform"] == "netease"
        assert job["target_platform"] == "bilibili"
        assert job["songs"][0]["status"] == "pending"
        # 映射查询已按设置生成(kotoha → MARUMOCHI_LABEL 在设置映射中)
        assert any("MARUMOCHI_LABEL" in q for q in job["songs"][0]["queries"])


def test_import_seeded_no_search_and_apply(test_app, tmp_path, monkeypatch):
    _isolated(tmp_path, monkeypatch)
    with TestClient(test_app) as client:
        resp = client.post(
            "/api/match/import",
            json={"name": "种子", "content": SEEDED_JSONL},
        )
        assert resp.status_code == 200
        # 种子任务无 pending,状态直接 done(不触发任何搜索)
        assert resp.json()["status"] == "done"

        # 应用到播放列表
        resp = client.post("/api/match/apply", json={"netease_ids": [3]})
        assert resp.status_code == 200
        r = resp.json()
        assert r["added"] == 1 and r["skipped_duplicates"] == 0 and r["skipped_not_ready"] == 0

        # 再应用一遍:重复跳过
        resp = client.post("/api/match/apply", json={"netease_ids": [3]})
        assert resp.json()["skipped_duplicates"] == 1

        # 歌单落盘且无重复
        with TestClient(test_app) as c2:
            playlist = c2.get("/api/playlist").json()
        assert [t["id"] for t in playlist] == ["bvBVTESTAA1"]


def test_choose_flow(test_app, tmp_path, monkeypatch):
    _isolated(tmp_path, monkeypatch)
    with TestClient(test_app) as client:
        client.post("/api/match/import", json={"name": "t", "content": NETEASE_JSON})
        # 未搜索的歌无候选:bvid 不在候选 → 400
        resp = client.post("/api/match/choose", json={"netease_id": 1, "bvid": "BVfake"})
        assert resp.status_code == 400

        # 标记无匹配
        resp = client.post("/api/match/choose", json={"netease_id": 1, "bvid": None})
        assert resp.status_code == 200
        assert resp.json()["status"] == "no_match"
        assert resp.json()["manual"] is True


def test_import_while_searching_409(test_app, tmp_path, monkeypatch):
    _isolated(tmp_path, monkeypatch)
    manager._job = {"status": "searching", "songs": []}
    with TestClient(test_app) as client:
        resp = client.post(
            "/api/match/import", json={"name": "t", "content": NETEASE_JSON}
        )
        assert resp.status_code == 409
        resp = client.post("/api/match/reset")
        assert resp.status_code == 409


def test_import_invalid_400(test_app, tmp_path, monkeypatch):
    _isolated(tmp_path, monkeypatch)
    with TestClient(test_app) as client:
        resp = client.post(
            "/api/match/import", json={"name": "t", "content": "这不是任何格式"}
        )
        assert resp.status_code == 400


def test_apply_not_ready_skipped(test_app, tmp_path, monkeypatch):
    _isolated(tmp_path, monkeypatch)
    with TestClient(test_app) as client:
        client.post("/api/match/import", json={"name": "t", "content": NETEASE_JSON})
        resp = client.post("/api/match/apply", json={"netease_ids": [1, 2]})
        r = resp.json()
        assert r["added"] == 0 and r["skipped_duplicates"] == 0 and r["skipped_not_ready"] == 2


def test_placeholder_add_all_and_dedupe(test_app, tmp_path, monkeypatch):
    _isolated(tmp_path, monkeypatch)
    with TestClient(test_app) as client:
        client.post("/api/match/import", json={"name": "t", "content": NETEASE_JSON})
        resp = client.post("/api/match/placeholder", json={})
        assert resp.status_code == 200 and resp.json()["added"] == 2

        with TestClient(test_app) as c2:
            playlist = c2.get("/api/playlist").json()
        ids = [t["id"] for t in playlist]
        assert ids == ["match:1", "match:2"]
        p1 = playlist[0]
        assert p1["title"] == "不完全花" and p1["source"] == "待匹配"
        assert p1["orig_name"] == "不完全花" and p1["orig_artists"] == ["kotoha"]
        assert p1["match_netease_id"] == 1

        # 再点一遍:不重复
        resp = client.post("/api/match/placeholder", json={})
        assert resp.json()["added"] == 0


def test_placeholder_add_selected_ids(test_app, tmp_path, monkeypatch):
    _isolated(tmp_path, monkeypatch)
    with TestClient(test_app) as client:
        client.post("/api/match/import", json={"name": "t", "content": NETEASE_JSON})
        resp = client.post("/api/match/placeholder", json={"netease_ids": [1]})
        assert resp.json()["added"] == 1
        with TestClient(test_app) as c2:
            playlist = c2.get("/api/playlist").json()
        assert [t["id"] for t in playlist] == ["match:1"]


def test_apply_upgrades_placeholder_in_place(test_app, tmp_path, monkeypatch):
    _isolated(tmp_path, monkeypatch)
    with TestClient(test_app) as client:
        client.post("/api/match/import", json={"name": "种子", "content": SEEDED_JSONL})
        # 先加占位(种子任务的歌 nid=3),再 apply → 就地升级
        client.post("/api/match/placeholder", json={"netease_ids": [3]})
        resp = client.post("/api/match/apply", json={"netease_ids": [3]})
        r = resp.json()
        assert r["upgraded"] == 1 and r["added"] == 0

        with TestClient(test_app) as c2:
            playlist = c2.get("/api/playlist").json()
        assert len(playlist) == 1  # 无重复
        t = playlist[0]
        assert t["id"] == "bvBVTESTAA1"
        assert t["title"] == "夏恋慕" and t["source"] == "bilibili 视频"
        assert t["orig_name"] == "夏恋慕" and t["match_netease_id"] == 3


def test_apply_removes_placeholder_when_bvid_exists_elsewhere(test_app, tmp_path, monkeypatch):
    _isolated(tmp_path, monkeypatch)
    with TestClient(test_app) as client:
        client.post("/api/match/import", json={"name": "种子", "content": SEEDED_JSONL})
        # 先直接 apply 加入真实 bvid,再人为放一个占位 → apply 时应移除占位不产生重复
        client.post("/api/match/apply", json={"netease_ids": [3]})
        with TestClient(test_app) as c2:
            playlist = c2.get("/api/playlist").json()
        playlist.append({"id": "match:3", "title": "夏恋慕", "artist": "", "mid": 0,
                         "cover": "", "duration": 200, "source": "待匹配",
                         "orig_name": "夏恋慕", "orig_artists": [], "match_netease_id": 3})
        client.put("/api/playlist", json=playlist)
        resp = client.post("/api/match/apply", json={"netease_ids": [3]})
        r = resp.json()
        assert r["removed_duplicates"] == 1 and r["added"] == 0 and r["upgraded"] == 0
        with TestClient(test_app) as c2:
            playlist = c2.get("/api/playlist").json()
        assert [t["id"] for t in playlist] == ["bvBVTESTAA1"]
