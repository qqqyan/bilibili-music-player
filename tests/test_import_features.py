"""B站收藏夹 / 音频歌单导入与 au 音频解析测试(全部离线)。"""

import asyncio

from fastapi.testclient import TestClient

from bilibili_music_player.services import audio_list_service, favorites_service, parse_service


# ---------------------------------------------------------------- 收藏夹服务


def test_folders_without_login_returns_empty(monkeypatch):
    monkeypatch.setattr(favorites_service, "current_mid", lambda: None)
    data = asyncio.run(favorites_service.list_folders())
    assert data == {"logged_in": False, "mid": None, "items": []}


def test_folders_maps_public_folders(monkeypatch):
    async def fake_folders(uid, credential=None):
        assert uid == 32708543
        return {
            "count": 1,
            "list": [
                {
                    "id": 4371982843,
                    "fid": 43719828,
                    "title": "联名2AI MV赛道",
                    "media_count": 6,
                    "cover": "//i1.hdslb.com/a.jpg",
                }
            ],
        }

    monkeypatch.setattr(favorites_service, "current_mid", lambda: 123)
    monkeypatch.setattr(
        favorites_service.favorite_list, "get_video_favorite_list", fake_folders
    )
    data = asyncio.run(favorites_service.list_folders(32708543))
    assert data["logged_in"] is True
    assert data["items"] == [
        {
            "media_id": 4371982843,
            "fid": 43719828,
            "title": "联名2AI MV赛道",
            "count": 6,
            "cover": "https://i1.hdslb.com/a.jpg",
        }
    ]


def test_favorites_items_maps_video_entries(monkeypatch):
    async def fake_content(media_id, page=1, credential=None):
        assert media_id == 1000
        assert page == 1
        return {
            "info": {
                "title": "测试收藏夹",
                "media_count": 2,
                "cover": "//i0.hdslb.com/c.jpg",
                "upper": {"name": "UP主"},
            },
            "medias": [
                {
                    "type": 2,
                    "bvid": "BV1xx411c7mD",
                    "title": "视频一",
                    "duration": 100,
                    "cover": "//i0.hdslb.com/1.jpg",
                    "upper": {"mid": 7, "name": "UP"},
                },
                {"type": 1, "bvid": "BV1yy411c7mD", "title": "专栏"},
            ],
            "has_more": True,
        }

    monkeypatch.setattr(
        favorites_service.favorite_list, "get_video_favorite_list_content", fake_content
    )
    data = asyncio.run(favorites_service.list_items(1000))
    assert data["media"] == {
        "media_id": 1000,
        "title": "测试收藏夹",
        "count": 2,
        "cover": "https://i0.hdslb.com/c.jpg",
        "upper": "UP主",
    }
    assert data["has_more"] is True
    assert len(data["items"]) == 1
    item = data["items"][0]
    assert item.id == "bvBV1xx411c7mD"
    assert item.mid == 7
    assert item.source == "bilibili 视频"


def test_favorites_items_invalid_raises(monkeypatch):
    async def fake_content(*args, **kwargs):
        return None

    monkeypatch.setattr(
        favorites_service.favorite_list, "get_video_favorite_list_content", fake_content
    )
    try:
        asyncio.run(favorites_service.list_items(1))
    except ValueError as e:
        assert "不存在" in str(e)
    else:  # pragma: no cover
        raise AssertionError("无效收藏夹应抛 ValueError")


# ---------------------------------------------------------------- 音频歌单服务


class FakeAudioList:
    def __init__(self, amid, credential=None):
        self.amid = amid

    async def get_info(self):
        return {
            "title": "测试歌单",
            "cover": "//i0.hdslb.com/list.jpg",
            "uname": "UP",
            "intro": "简介",
            "snum": 2,
        }

    async def get_song_list(self, pn=1):
        return {
            "pageCount": 2,
            "totalSize": 2,
            "data": [
                {
                    "id": 2478206,
                    "bvid": "",
                    "title": "纯音频",
                    "author": "歌手A",
                    "uid": 123,
                    "duration": 112,
                    "cover": "//i0.hdslb.com/a.jpg",
                },
                {
                    "id": 2445151,
                    "bvid": "BV1bU4y1n7Nx",
                    "title": "视频曲目",
                    "uname": "UP",
                    "uid": 456,
                    "duration": 197,
                    "cover": "",
                },
            ],
        }


def test_audio_list_maps_both_track_types(monkeypatch):
    monkeypatch.setattr(audio_list_service.audio, "AudioList", FakeAudioList)
    data = asyncio.run(audio_list_service.get_list(10624, page=1))
    assert data["title"] == "测试歌单"
    assert data["count"] == 2
    assert data["has_more"] is True
    assert [i.id for i in data["items"]] == ["au2478206", "bvBV1bU4y1n7Nx"]
    assert data["items"][0].source == "bilibili 音频"
    assert data["items"][1].source == "bilibili 视频"


class FakeAudio:
    def __init__(self, auid, credential=None):
        self.auid = auid

    async def get_info(self):
        return {
            "title": "纯音频",
            "author": "歌手A",
            "uid": 123,
            "cover": "//i0.hdslb.com/a.jpg",
            "duration": 112,
        }

    async def get_download_url(self):
        return {"cdns": ["https://example.com/a.m4a"]}


def test_resolve_audio_track(monkeypatch):
    monkeypatch.setattr(parse_service.audio, "Audio", FakeAudio)
    track = asyncio.run(parse_service.resolve_track("au2478206"))
    assert track.id == "au2478206"
    assert track.source == "bilibili 音频"
    assert track.mid == 123
    assert track.duration == 112
    assert len(track.audio_streams) == 1
    assert track.audio_streams[0].quality == "标准"
    assert track.audio_streams[0].stream_url.startswith("/api/stream/")


def test_register_stream_keeps_bilibili_headers_when_mime_set():
    """只传 mime 时不能丢掉默认 UA/Referer(否则 B站 CDN 403)。"""
    from bilibili_music_player.services.stream_proxy import (
        REFERER,
        get_stream_headers,
        register_stream,
    )

    token = register_stream(["https://example.com/a.m4a"], mime="audio/mp4")
    headers = get_stream_headers(token)
    assert headers["Referer"] == REFERER
    assert headers["User-Agent"]


# ---------------------------------------------------------------- 路由


def test_folders_api(test_app, monkeypatch):
    async def fake(mid=None):
        return {"logged_in": False, "mid": None, "items": []}

    monkeypatch.setattr(
        "bilibili_music_player.routers.favorites.favorites_service.list_folders", fake
    )

    with TestClient(test_app) as client:
        resp = client.get("/api/favorites/folders")
    assert resp.status_code == 200
    assert resp.json()["logged_in"] is False


def test_favorites_items_api_error(test_app, monkeypatch):
    async def fake(media_id, page=1):
        raise ValueError("收藏夹不存在或不可见")

    monkeypatch.setattr(
        "bilibili_music_player.routers.favorites.favorites_service.list_items", fake
    )

    with TestClient(test_app) as client:
        resp = client.get("/api/favorites/1/items")
    assert resp.status_code == 404


def test_audiolist_api(test_app, monkeypatch):
    async def fake(am_id, page=1):
        return {"am_id": am_id, "items": [], "has_more": False}

    monkeypatch.setattr(
        "bilibili_music_player.routers.audiolist.audio_list_service.get_list", fake
    )

    with TestClient(test_app) as client:
        resp = client.get("/api/audiolist/10624")
    assert resp.status_code == 200
    assert resp.json()["am_id"] == 10624
