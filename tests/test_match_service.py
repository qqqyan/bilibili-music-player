"""歌单匹配服务纯函数测试:解析去重、种子状态映射、打分档位、映射查询。"""

import pytest

from bilibili_music_player.services import match_service as ms

ARTIST_MAP = [
    {"singer": "kotoha", "netease": ["kotoha", "コトハ"], "bilibili": ["MARUMOCHI_LABEL"]},
    {"singer": "ハコニワリリィ", "netease": ["ハコニワリリィ"], "bilibili": ["hothha", "hanon"]},
]


# ---------------------------------------------------------------- 归一化与映射

def test_resolve_target_names():
    names = ms.resolve_target_names(["kotoha"], ARTIST_MAP, "netease", "bilibili")
    assert names == ["MARUMOCHI_LABEL"]


def test_resolve_target_names_multi_artist():
    names = ms.resolve_target_names(
        ["ハコニワリリィ", "春茶"], ARTIST_MAP, "netease", "bilibili"
    )
    assert names == ["hothha", "hanon"]


def test_resolve_target_names_no_hit():
    assert ms.resolve_target_names(["Mili"], ARTIST_MAP, "netease", "bilibili") == []


def test_norm_artist_strips_official():
    assert ms._norm_artist("洛天依Official") == "洛天依"


# ---------------------------------------------------------------- 查询构建

def test_build_queries_alias_first_and_dedup():
    qs = ms.build_queries(
        "心做し", ["こはならむ"], [], [], ARTIST_MAP, "netease", "bilibili"
    )
    # 主歌手 + 歌名在最前,裸歌名在后
    assert qs[0] == "こはならむ 心做し"
    assert "心做し" in qs
    assert len(qs) == len(set(qs))


def test_build_queries_with_alias():
    qs = ms.build_queries(
        "夏、透明な青に惹かれて。", ["ハコニワリリィ"], [], [], ARTIST_MAP, "netease", "bilibili"
    )
    assert any("hothha" in q for q in qs)
    assert any("hanon" in q for q in qs)


def test_build_queries_tns_variant():
    qs = ms.build_queries(
        "花火のような恋", ["みゆはん"], ["花火般的恋爱"], [], [], "netease", "bilibili"
    )
    assert "みゆはん 花火般的恋爱" in qs
    assert "花火般的恋爱" in qs


# ---------------------------------------------------------------- 打分

def _song(name="心做し", artists=None, dur_s=300):
    return {"name": name, "artists": artists or ["こはならむ"], "duration_ms": int(dur_s * 1000)}


def test_score_exact_match_full():
    score, reason = ms.score_candidate(
        "心做し - こはならむ", "some_up", 300, 1000, "心做し", ["こはならむ"], 300, []
    )
    assert score >= 100  # 80 标题 + 20 歌手 + 播放加分
    assert "标题含歌名" in reason


def test_score_album_exclude():
    score, _ = ms.score_candidate(
        "【合集】一人一首 心做し", "some_up", 300, 1000, "心做し", ["こはならむ"], 300, []
    )
    assert score == 0


def test_score_cover_penalty():
    base, _ = ms.score_candidate(
        "心做し", "some_up", 300, 1000, "心做し", ["こはならむ"], 300, []
    )
    cover, _ = ms.score_candidate(
        "【翻唱】心做し", "some_up", 300, 1000, "心做し", ["こはならむ"], 300, []
    )
    assert cover == base - 25


def test_score_duration_bands():
    perfect, _ = ms.score_candidate("心做し", "u", 300, 0, "心做し", ["a"], 300, [])
    near, _ = ms.score_candidate("心做し", "u", 310, 0, "心做し", ["a"], 300, [])
    far, _ = ms.score_candidate("心做し", "u", 400, 0, "心做し", ["a"], 300, [])
    assert perfect - near == 15
    assert perfect - far == 60


def test_score_alias_bonus_in_title():
    song = _song("夏、透明な青に惹かれて。", ["ハコニワリリィ"])
    aliases = ms.resolve_target_names(song["artists"], ARTIST_MAP, "netease", "bilibili")
    score, reason = ms.score_candidate(
        "夏、透明な青に惹かれて。/ hothha", "u", 240, 0,
        song["name"], song["artists"], 240, aliases,
    )
    assert "映射歌手" in reason


def test_score_alias_bonus_up():
    song = _song("不完全花", ["kotoha"])
    aliases = ms.resolve_target_names(song["artists"], ARTIST_MAP, "netease", "bilibili")
    score, reason = ms.score_candidate(
        "不完全花", "MARUMOCHI_LABEL", 220, 0,
        song["name"], song["artists"], 220, aliases,
    )
    assert "映射歌手" in reason


def test_score_single_char_name_no_false_containment():
    # 「x」单字歌名不因包含关系误判:相似度路径给分,远低于阈值
    score, _ = ms.score_candidate(
        "xxx视频", "u", 235, 0, "x", ["平葵"], 235, []
    )
    assert score < ms.AUTO_SCORE


# ---------------------------------------------------------------- 解析

def test_parse_netease_dedup_keeps_longest():
    data = [
        {"id": 1, "name": "心做し", "ar": [{"name": "こはならむ"}], "dt": 200000, "tns": [], "alia": []},
        {"id": 2, "name": "心做し", "ar": [{"name": "こはならむ"}], "dt": 250000, "tns": [], "alia": []},
    ]
    songs = ms.parse_netease_json(data, [], "netease", "bilibili")
    assert len(songs) == 1
    assert songs[0]["netease_id"] == 2
    assert songs[0]["status"] == "pending"


def test_parse_netease_invalid():
    with pytest.raises(ValueError):
        ms.parse_netease_json([{"no_name": 1}], [], "netease", "bilibili")
    with pytest.raises(ValueError):
        ms.parse_netease_json([], [], "netease", "bilibili")


def test_parse_seeded_status_mapping():
    text = "\n".join([
        '{"netease_id": 1, "name": "a", "artists": ["x"], "duration_ms": 1000,'
        ' "status": "matched", "chosen": {"bvid": "BV1", "title": "a - x", "up": "x",'
        ' "mid": 1, "cover": "", "duration_s": 1, "play": 10, "score": 90},'
        ' "candidates": [{"bvid": "BV1", "title": "a - x", "up": "x", "mid": 1,'
        ' "cover": "", "duration_s": 1, "play": 10, "score": 90}]}',
        '{"netease_id": 2, "name": "b", "artists": ["y"], "duration_ms": 2000,'
        ' "status": "review", "chosen": {"bvid": "BV2", "title": "b - y", "up": "y",'
        ' "mid": 2, "cover": "", "duration_s": 2, "play": 5, "score": 50},'
        ' "candidates": [{"bvid": "BV2", "title": "b - y", "up": "y", "mid": 2,'
        ' "cover": "", "duration_s": 2, "play": 5, "score": 50}]}',
        '{"netease_id": 3, "name": "c", "artists": ["z"], "duration_ms": 3000,'
        ' "status": "review", "chosen": null, "candidates": []}',
        "broken line not json",
    ])
    songs = ms.parse_seeded_jsonl(text, [], "netease", "bilibili")
    by_id = {s["netease_id"]: s for s in songs}
    assert len(songs) == 3  # 坏行被跳过
    assert by_id[1]["status"] == "matched" and by_id[1]["chosen"]["bvid"] == "BV1"
    # review 的 chosen 必须清空(临时脚本对 review 也写了 chosen)
    assert by_id[2]["status"] == "review" and by_id[2]["chosen"] is None
    assert by_id[3]["status"] == "no_match"


def test_parse_seeded_invalid():
    with pytest.raises(ValueError):
        ms.parse_seeded_jsonl("not json at all", [], "netease", "bilibili")


def test_parse_netease_captures_pic_url():
    data = [{
        "id": 1, "name": "铁花飞",
        "ar": [{"name": "Mili"}], "dt": 242613, "tns": [], "alia": [],
        "al": {"picUrl": "http://p2.music.126.net/abc.jpg"},
    }]
    songs = ms.parse_netease_json(data, [], "netease", "bilibili")
    assert songs[0]["cover"] == "http://p2.music.126.net/abc.jpg"


def test_placeholder_track_shape():
    song = {
        "netease_id": 7, "name": "夜妆", "artists": ["洛天依Official", "苏逸"],
        "duration_ms": 200000, "cover": "http://x/1.jpg",
    }
    t = ms._placeholder_track(song)
    assert t["id"] == "match:7"
    assert t["source"] == "待匹配"
    assert t["orig_name"] == "夜妆"
    assert t["orig_artists"] == ["洛天依Official", "苏逸"]
    assert t["duration"] == 200
    assert t["match_netease_id"] == 7


# ---------------------------------------------------------------- lazy_resolve
# 单例管理器:测试内重置状态 + 隔离任务文件,异步用 asyncio.run 驱动。

import asyncio  # noqa: E402


def _isolated_manager(tmp_path, monkeypatch):
    """隔离 manager 状态与任务/设置文件,返回 (manager, run)。"""
    from bilibili_music_player.repositories import match_store, settings_store

    ms.manager._job = None
    ms.manager._pause_requested = False
    monkeypatch.setattr(match_store, "MATCH_FILE", tmp_path / "match_job.json")
    monkeypatch.setattr(settings_store, "SETTINGS_FILE", tmp_path / "settings.json")

    async def run(coro):
        return await coro

    return ms.manager, run


def test_lazy_resolve_uses_chosen_without_search(tmp_path, monkeypatch):
    manager, run = _isolated_manager(tmp_path, monkeypatch)
    chosen = {"bvid": "BVAAA", "title": "t", "up": "u", "mid": 1,
              "cover": "", "duration_s": 10, "play": 5, "score": 90}
    manager._job = {"songs": [{"netease_id": 1, "name": "a", "artists": ["x"],
                               "status": "matched", "chosen": chosen}]}
    called = []

    async def fake_fetch(q, stat):
        called.append(q)

    monkeypatch.setattr(ms, "_fetch_candidates", fake_fetch)
    real_id, cand = asyncio.run(manager.lazy_resolve(1))
    assert real_id == "bvBVAAA" and cand is chosen and not called


def test_lazy_resolve_promotes_high_score_candidate(tmp_path, monkeypatch):
    manager, run = _isolated_manager(tmp_path, monkeypatch)
    cand = {"bvid": "BVB", "title": "t", "up": "u", "mid": 1,
            "cover": "", "duration_s": 10, "play": 5, "score": 90}
    song = {"netease_id": 1, "name": "a", "artists": ["x"], "duration_ms": 10000,
            "status": "review", "chosen": None, "queries": ["x a"], "candidates": [cand]}
    manager._job = {"songs": [song], "source_platform": "netease"}
    real_id, got = asyncio.run(manager.lazy_resolve(1))
    assert real_id == "bvBVB" and got is cand
    assert song["status"] == "matched" and song["chosen"] is cand


def test_lazy_resolve_low_score_not_promoted(tmp_path, monkeypatch):
    manager, run = _isolated_manager(tmp_path, monkeypatch)
    cand = {"bvid": "BVB", "title": "t", "up": "u", "mid": 1,
            "cover": "", "duration_s": 10, "play": 5, "score": 30}
    song = {"netease_id": 1, "name": "a", "artists": ["x"], "duration_ms": 10000,
            "status": "review", "chosen": None, "queries": ["x a"], "candidates": [cand]}
    manager._job = {"songs": [song]}
    real_id, got = asyncio.run(manager.lazy_resolve(1))
    assert real_id == "bvBVB" and got is cand
    assert song["chosen"] is None and song["status"] == "review"


def test_lazy_resolve_searching_song_not_persisted(tmp_path, monkeypatch):
    manager, run = _isolated_manager(tmp_path, monkeypatch)
    cand = {"bvid": "BVB", "title": "t", "up": "u", "mid": 1,
            "cover": "", "duration_s": 10, "play": 5, "score": 90}
    song = {"netease_id": 1, "name": "a", "artists": ["x"], "duration_ms": 10000,
            "status": "searching", "chosen": None, "queries": ["x a"], "candidates": [cand]}
    manager._job = {"songs": [song]}
    real_id, _ = asyncio.run(manager.lazy_resolve(1))
    assert real_id == "bvBVB"
    assert song["chosen"] is None and song["status"] == "searching"


def test_lazy_resolve_live_search_fallback(tmp_path, monkeypatch):
    manager, run = _isolated_manager(tmp_path, monkeypatch)
    manager._job = None  # 任务被重置,只剩播放列表条目
    searched = []

    async def fake_fetch(q, stat):
        searched.append(q)
        return [ms.to_candidate({"bvid": "BVX", "title": "夜妆 洛天依", "author": "某UP",
                                 "mid": 1, "pic": "", "duration": "3:30", "play": "10"})]

    monkeypatch.setattr(ms, "_fetch_candidates", fake_fetch)
    real_id, cand = asyncio.run(
        manager.lazy_resolve(9, fallback_name="夜妆", fallback_artists=["洛天依Official"])
    )
    assert real_id == "bvBVX" and cand["bvid"] == "BVX"
    # 单搜索语义:第一个有结果的查询即止
    assert searched == ["洛天依 夜妆"]
    assert manager._job is None  # 不落盘


def test_lazy_resolve_no_candidates_raises(tmp_path, monkeypatch):
    manager, run = _isolated_manager(tmp_path, monkeypatch)
    manager._job = None

    async def fake_fetch(q, stat):
        return []

    monkeypatch.setattr(ms, "_fetch_candidates", fake_fetch)
    with pytest.raises(ValueError, match="匹配失败"):
        asyncio.run(manager.lazy_resolve(9, fallback_name="不存在的歌", fallback_artists=[]))


def test_lazy_resolve_manual_no_match_raises(tmp_path, monkeypatch):
    manager, run = _isolated_manager(tmp_path, monkeypatch)
    song = {"netease_id": 1, "name": "a", "artists": ["x"], "status": "no_match",
            "chosen": None, "manual": True, "candidates": []}
    manager._job = {"songs": [song]}
    with pytest.raises(ValueError, match="已手动标记无匹配"):
        asyncio.run(manager.lazy_resolve(1))
