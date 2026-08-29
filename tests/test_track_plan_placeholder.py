"""track plan 占位曲目 hook 测试:match:{nid} 即时匹配为真实 bvid(无网络)。"""

from fastapi.testclient import TestClient

from bilibili_music_player import quality


class FakeStream:
    def __init__(self, quality_id, label):
        self.quality_id = quality_id
        self.quality = label
        self.mime = "audio/mp4"
        self.stream_url = "/api/stream/faketoken"


class FakeResolved:
    def __init__(self):
        self.id = "bvFAKE1"
        self.title = "假视频"
        self.artist = "假UP"
        self.mid = 0
        self.cover = ""
        self.duration = 200
        self.source = "bilibili 视频"
        self.audio_streams = [FakeStream(quality.QUALITY_ORDER[0], "64K")]
        self.video_streams = []


def _patch_plan_deps(monkeypatch, lazy_result):
    """替换 plan 端点的下游依赖,捕获 real_id 使用点。"""
    calls = {}

    async def fake_lazy(nid, fallback_name="", fallback_artists=None):
        calls["lazy_nid"] = nid
        calls["lazy_fallback_name"] = fallback_name
        calls["lazy_fallback_artists"] = fallback_artists
        if isinstance(lazy_result, Exception):
            raise lazy_result
        return lazy_result

    async def fake_resolve(track_id, page_index=0):
        calls["resolve_id"] = track_id
        return FakeResolved()

    async def fake_prioritize(track_id):
        calls["prioritize_id"] = track_id

    async def fake_local(track_id):
        calls["cache_id"] = track_id
        return []

    async def fake_playlist():
        return [{"id": "match:1", "title": "占位", "artist": "x", "mid": 0,
                 "cover": "", "duration": 100, "source": "待匹配",
                 "orig_name": "夜妆", "orig_artists": ["洛天依Official"],
                 "match_netease_id": 1}]

    monkeypatch.setattr(
        "bilibili_music_player.routers.track.match_manager.lazy_resolve", fake_lazy
    )
    monkeypatch.setattr(
        "bilibili_music_player.routers.track.match_manager.demote_chosen",
        lambda nid, bvid: None,
    )
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
    monkeypatch.setattr(
        "bilibili_music_player.routers.track.playlist_store.get_playlist", fake_playlist
    )
    return calls


def test_plan_placeholder_resolves_to_real_bvid(test_app, monkeypatch):
    calls = _patch_plan_deps(monkeypatch, ("bvFAKE1", {"bvid": "FAKE1"}))
    with TestClient(test_app) as client:
        resp = client.get("/api/track/match:1/plan")
    assert resp.status_code == 200
    data = resp.json()
    assert data["track"]["id"] == "bvFAKE1"
    assert data["match_chosen"] == {"bvid": "FAKE1"}
    # 下游全部使用真实 bvid;fallback 名/歌手来自播放列表条目
    assert calls["lazy_nid"] == 1
    assert calls["lazy_fallback_name"] == "夜妆"
    assert calls["lazy_fallback_artists"] == ["洛天依Official"]
    assert calls["prioritize_id"] == "bvFAKE1"
    assert calls["resolve_id"] == "bvFAKE1"
    assert calls["cache_id"] == "bvFAKE1"


def test_plan_placeholder_match_failure_502(test_app, monkeypatch):
    _patch_plan_deps(monkeypatch, ValueError("匹配失败:未找到候选"))
    with TestClient(test_app) as client:
        resp = client.get("/api/track/match:1/plan")
    assert resp.status_code == 502
    assert "匹配失败" in resp.json()["detail"]


def test_plan_placeholder_bad_id_400(test_app, monkeypatch):
    with TestClient(test_app) as client:
        resp = client.get("/api/track/match:notanumber/plan")
    assert resp.status_code == 400
