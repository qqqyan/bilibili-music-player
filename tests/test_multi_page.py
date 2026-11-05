"""多 P 视频分 P 选择:ID 规则、分 P 解析与接口测试(无网络)。"""

import asyncio

from fastapi.testclient import TestClient

from bilibili_music_player.models import ResolvedTrack
from bilibili_music_player.repositories import cache_store
from bilibili_music_player.services import parse_service


def test_split_page_suffix_plain_id():
    assert parse_service.split_page_suffix("bvBV1xx411c7mD") == ("bvBV1xx411c7mD", None)


def test_split_page_suffix_with_page():
    assert parse_service.split_page_suffix("bvBV1xx411c7mD_p3") == (
        "bvBV1xx411c7mD",
        2,
    )


def test_split_page_suffix_first_page_normalized():
    # _p1 与无后缀等价,统一下标 0
    assert parse_service.split_page_suffix("bvBV1xx411c7mD_p1") == (
        "bvBV1xx411c7mD",
        0,
    )


def test_split_page_suffix_ignores_non_bv_ids():
    assert parse_service.split_page_suffix("ne123") == ("ne123", None)
    assert parse_service.split_page_suffix("match:1") == ("match:1", None)


def test_page_track_id_roundtrip():
    base = "bvBV1xx411c7mD"
    assert parse_service.page_track_id(base, 0) == base
    assert parse_service.page_track_id(base, 4) == f"{base}_p5"
    assert parse_service.split_page_suffix(f"{base}_p5") == (base, 4)


def test_cache_path_accepts_page_suffix():
    # 每个分 P 独立缓存目录:bv..._p2 必须是合法目录名
    cache_store.validate_track_id("bvBV1xx411c7mD_p2")


def test_resolve_track_uses_page_suffix(monkeypatch):
    """resolve_track 从 id 后缀取分 P,并把规范 id 交给 _resolve_video。"""
    calls = {}

    async def fake_resolve_video(bvid, page_index, track_id=None):
        calls.update(bvid=bvid, page_index=page_index, track_id=track_id)
        return ResolvedTrack(
            id=track_id or f"bv{bvid}",
            title="分 P 标题",
            artist="UP",
            cover="",
            duration=100,
            source="bilibili 视频",
            audio_streams=[],
        )

    monkeypatch.setattr(parse_service, "_resolve_video", fake_resolve_video)
    resolved = asyncio.run(parse_service.resolve_track("bvBV1xx411c7mD_p3"))
    assert calls == {
        "bvid": "BV1xx411c7mD",
        "page_index": 2,
        "track_id": "bvBV1xx411c7mD_p3",
    }
    assert resolved.id == "bvBV1xx411c7mD_p3"


def test_resolve_track_explicit_page_without_suffix(monkeypatch):
    """旧调用方仍可用 page_index 参数;返回 id 规范化为带后缀。"""
    calls = {}

    async def fake_resolve_video(bvid, page_index, track_id=None):
        calls.update(bvid=bvid, page_index=page_index, track_id=track_id)
        return ResolvedTrack(
            id=track_id or f"bv{bvid}",
            title="分 P 标题",
            artist="UP",
            cover="",
            duration=100,
            source="bilibili 视频",
            audio_streams=[],
        )

    monkeypatch.setattr(parse_service, "_resolve_video", fake_resolve_video)
    resolved = asyncio.run(parse_service.resolve_track("bvBV1xx411c7mD", 1))
    assert calls["page_index"] == 1
    assert resolved.id == "bvBV1xx411c7mD_p2"


def test_resolve_track_suffix_wins_over_explicit_page(monkeypatch):
    calls = {}

    async def fake_resolve_video(bvid, page_index, track_id=None):
        calls.update(page_index=page_index, track_id=track_id)
        return ResolvedTrack(
            id=track_id,
            title="分 P 标题",
            artist="UP",
            cover="",
            duration=100,
            source="bilibili 视频",
            audio_streams=[],
        )

    monkeypatch.setattr(parse_service, "_resolve_video", fake_resolve_video)
    asyncio.run(parse_service.resolve_track("bvBV1xx411c7mD_p3", 0))
    assert calls["page_index"] == 2


def test_get_video_pages_maps_fields(monkeypatch):
    class FakeVideo:
        def __init__(self, bvid, credential=None):
            self.bvid = bvid

        async def get_pages(self):
            return [
                {
                    "page": 1,
                    "part": "第一首",
                    "duration": 212,
                    "first_frame": "//i0.hdslb.com/a.jpg",
                },
                {"page": 2, "part": "第二首", "duration": 227, "first_frame": ""},
            ]

    monkeypatch.setattr(parse_service.video, "Video", FakeVideo)
    pages = asyncio.run(parse_service.get_video_pages("bvBV1xx411c7mD_p2"))
    assert pages[0] == {
        "index": 0,
        "page": 1,
        "title": "第一首",
        "duration": 212,
        "cover": "https://i0.hdslb.com/a.jpg",
    }
    assert pages[1]["index"] == 1
    assert pages[1]["page"] == 2


def test_get_video_pages_rejects_non_bv():
    try:
        asyncio.run(parse_service.get_video_pages("ne123"))
    except ValueError as e:
        assert "分 P" in str(e)
    else:  # pragma: no cover - 反向断言
        raise AssertionError("非 bilibili 视频应拒绝分 P 查询")


def test_pages_api(test_app, monkeypatch):
    async def fake_pages(track_id):
        assert track_id == "bvBV1xx411c7mD_p2"
        return [{"index": 0, "page": 1, "title": "A", "duration": 10, "cover": ""}]

    monkeypatch.setattr(
        "bilibili_music_player.routers.track.get_video_pages", fake_pages
    )
    with TestClient(test_app) as client:
        resp = client.get("/api/video/bvBV1xx411c7mD_p2/pages")
    assert resp.status_code == 200
    assert resp.json()["pages"][0]["title"] == "A"


def test_pages_api_error_502(test_app, monkeypatch):
    async def fake_pages(track_id):
        raise ValueError("获取分 P 失败")

    monkeypatch.setattr(
        "bilibili_music_player.routers.track.get_video_pages", fake_pages
    )
    with TestClient(test_app) as client:
        resp = client.get("/api/video/bvBV1xx411c7mD/pages")
    assert resp.status_code == 502
    assert "分 P" in resp.json()["detail"]


def test_build_video_track_page_count_and_title():
    track = parse_service._build_video_track(
        {
            "title": "总标题",
            "pages": [{"page": 1}, {"page": 2}],
            "owner": {"name": "UP"},
        },
        {"part": "第二首", "duration": 227},
        "BV1xx411c7mD",
        "bvBV1xx411c7mD_p2",
    )
    assert track.id == "bvBV1xx411c7mD_p2"
    assert track.title == "总标题 - 第二首"
    assert track.page_count == 2


def test_plan_uses_page_suffix_id(test_app, monkeypatch):
    """plan 端点对带分 P 后缀的曲目全程使用完整 ID(缓存/下载/解析)。"""
    calls = {}

    async def fake_resolve(track_id, page_index=None):
        calls["resolve_id"] = track_id
        return ResolvedTrack(
            id=track_id,
            title="总标题 - 第二首",
            artist="UP",
            cover="",
            duration=227,
            source="bilibili 视频",
            audio_streams=[],
        )

    async def fake_prioritize(track_id):
        calls["prioritize_id"] = track_id

    async def fake_local(track_id):
        calls["cache_id"] = track_id
        return []

    monkeypatch.setattr("bilibili_music_player.routers.track.resolve_track", fake_resolve)
    monkeypatch.setattr(
        "bilibili_music_player.routers.track.download_manager.prioritize", fake_prioritize
    )
    monkeypatch.setattr(
        "bilibili_music_player.routers.track.cache_store.get_local_qualities", fake_local
    )
    monkeypatch.setattr(
        "bilibili_music_player.routers.track.cache_store.get_local_videos", fake_local
    )
    with TestClient(test_app) as client:
        resp = client.get("/api/track/bvBV1xx411c7mD_p2/plan")
    assert resp.status_code == 200
    assert resp.json()["track"]["id"] == "bvBV1xx411c7mD_p2"
    assert resp.json()["track"]["page_count"] == 1  # 默认单 P
    assert calls["resolve_id"] == "bvBV1xx411c7mD_p2"
    assert calls["prioritize_id"] == "bvBV1xx411c7mD_p2"
    assert calls["cache_id"] == "bvBV1xx411c7mD_p2"
