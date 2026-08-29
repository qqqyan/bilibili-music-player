"""网易云功能测试:加密结构/字段映射/存储/路由(网络调用全部 mock)。"""

import base64

from fastapi.testclient import TestClient
from Cryptodome.Cipher import AES

from bilibili_music_player.repositories import netease_auth_store
from bilibili_music_player.routers import netease as ne_router
from bilibili_music_player.services import netease as ne


def test_weapi_structure():
    enc = ne.weapi({"type": 1})
    assert len(enc["encSecKey"]) == 256
    assert int(enc["encSecKey"], 16) > 0  # 合法 hex
    raw = base64.b64decode(enc["params"])
    assert len(raw) % 16 == 0
    # 第一层用固定密钥可解,内层仍为整块密文
    cipher = AES.new(b"0CoJUm6Qyw8W8jud", AES.MODE_CBC, b"0102030405060708")
    assert len(cipher.decrypt(raw)) % 16 == 0


def test_song_to_track_mapping():
    s = {
        "id": 123, "name": "夜妆", "dt": 200000,
        "artists": [{"name": "洛天依Official"}, {"name": "苏逸"}],
        "album": {"name": "四重奏", "picUrl": "http://p2.music.126.net/x.jpg"},
    }
    t = ne_router._song_to_track(s)
    assert t.id == "ne123" and t.source == "网易云音乐"
    assert t.artist == "洛天依Official、苏逸"
    assert t.album == "四重奏" and t.duration == 200
    assert t.cover == "http://p2.music.126.net/x.jpg"


def test_auth_store_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(netease_auth_store, "AUTH_FILE", tmp_path / "ne_auth.json")
    netease_auth_store.save_auth("MUSIC_U=abc; __csrf=def", {"name": "tester"})
    rec = netease_auth_store.load_auth()
    assert rec["cookie"] == "MUSIC_U=abc; __csrf=def"
    assert rec["user"]["name"] == "tester"
    netease_auth_store.clear_auth()
    assert netease_auth_store.load_auth() is None


def test_cache_ext_for_netease():
    from bilibili_music_player.repositories import cache_store

    assert cache_store._file_path("ne12345", 320000).name == "q320000.mp3"
    assert cache_store._file_path("ne12345", 999000).name == "q999000.flac"
    assert cache_store._file_path("bvBV1xx", 30280).name == "q30280.m4a"


def test_qrcode_flow_mocked(test_app, tmp_path, monkeypatch):
    """完整 QR 流程:scan → confirm → done,登录态落盘;会话消费后 404。"""
    monkeypatch.setattr(netease_auth_store, "AUTH_FILE", tmp_path / "ne_auth.json")
    monkeypatch.setattr(ne, "qr_svg", lambda k: "<svg></svg>")
    states = iter([
        ("scan", {}, ""),
        ("confirm", {"nickname": "tester"}, ""),
        ("done", {}, "MUSIC_U=abc; __csrf=def; NMTID=x"),
    ])

    class _DummyClient:
        def close(self):
            pass

    class FakeQr:
        def __init__(self):
            self.client = _DummyClient()

        def create_qr(self):
            return "unikey-1"

        def poll(self):
            return next(states)

        def close(self):
            pass

    monkeypatch.setattr(ne, "QrSession", FakeQr)
    monkeypatch.setattr(ne, "user_detail", lambda cookie: {"name": "tester", "face": ""})
    with TestClient(test_app) as client:
        r = client.post("/api/netease/qrcode")
        assert r.status_code == 200
        data = r.json()
        assert data["image_data_url"].startswith("data:image/svg+xml")
        sid = data["session_id"]
        assert client.get(f"/api/netease/qrcode/status/{sid}").json()["status"] == "scan"
        assert client.get(f"/api/netease/qrcode/status/{sid}").json()["status"] == "confirm"
        done = client.get(f"/api/netease/qrcode/status/{sid}").json()
        assert done["status"] == "done" and done["user"]["name"] == "tester"
        assert client.get("/api/netease/status").json()["logged_in"] is True
        # 会话已消费
        assert client.get(f"/api/netease/qrcode/status/{sid}").status_code == 404
        client.post("/api/netease/logout")
        assert client.get("/api/netease/status").json()["logged_in"] is False


def test_plan_ne_falls_back_to_cache_when_not_logged_in(test_app, tmp_path, monkeypatch):
    """未登录/无版权时 ne 曲目解析失败:已有缓存则 plan 仍可用本地档。"""
    import asyncio

    from bilibili_music_player.repositories import cache_store

    cache_dir = tmp_path / "cache"
    monkeypatch.setattr(cache_store, "CACHE_DIR", cache_dir)
    # 预置:缓存文件 + meta(下载时记录)
    (cache_dir / "ne1").mkdir(parents=True)
    (cache_dir / "ne1" / "q320000.mp3").write_bytes(b"x")
    asyncio.run(
        cache_store.save_downloaded(
            "ne1", 320000,
            {"title": "心音", "artist": "洛天依Official", "cover": "",
             "duration": 201, "source": "网易云音乐", "has_video": False},
            "audio",
        )
    )

    async def fake_resolve_fail(track_id, page_index=0):
        raise ValueError("未获取到播放地址(可能需登录或该歌曲无版权)")

    async def fake_prioritize(track_id):
        pass

    monkeypatch.setattr("bilibili_music_player.routers.track.resolve_track", fake_resolve_fail)
    monkeypatch.setattr(
        "bilibili_music_player.routers.track.download_manager.prioritize", fake_prioritize
    )
    with TestClient(test_app) as client:
        r = client.get("/api/track/ne1/plan")
    assert r.status_code == 200
    data = r.json()
    assert data["track"]["title"] == "心音"  # 元数据来自缓存
    assert data["audio_streams"] and data["audio_streams"][0]["local"] is True
    assert data["play"]["audio_local"] is True


def test_cookie_login_mocked(test_app, tmp_path, monkeypatch):
    """手动 cookie 导入:有效保存登录态,无效 400。"""
    monkeypatch.setattr(netease_auth_store, "AUTH_FILE", tmp_path / "ne_auth.json")
    monkeypatch.setattr(
        ne,
        "cookie_user",
        lambda cookie: {"name": "tester", "face": ""} if "MUSIC_U=ok" in cookie else None,
    )
    with TestClient(test_app) as client:
        # 无效 cookie
        r = client.post("/api/netease/cookie", json={"cookie": "MUSIC_U=bad"})
        assert r.status_code == 400
        # 有效 cookie
        r = client.post(
            "/api/netease/cookie", json={"cookie": "MUSIC_U=ok; __csrf=cs1"}
        )
        assert r.status_code == 200
        assert r.json()["user"]["name"] == "tester"
        st = client.get("/api/netease/status").json()
        assert st["logged_in"] is True


def test_search_mocked(test_app, monkeypatch):
    monkeypatch.setattr(
        ne,
        "search",
        lambda kw, page, cookie: (
            [{
                "id": 1, "name": "心音", "dt": 200000,
                "artists": [{"name": "洛天依Official"}],
                "album": {"name": "四重奏"},
            }],
            1,
        ),
    )
    with TestClient(test_app) as client:
        r = client.get("/api/netease/search", params={"keyword": "心音"})
        assert r.status_code == 200
        data = r.json()
        assert data["items"][0]["id"] == "ne1"
        assert data["items"][0]["album"] == "四重奏"
        assert data["has_more"] is False
