"""下载队列的决策纯函数测试(不依赖网络)。"""

from bilibili_music_player.services.download_manager import (
    _local_satisfies,
    _pick_desired_stream,
)


class FakeStream:
    def __init__(self, quality_id):
        self.quality_id = quality_id


def make_streams(ids):
    return [FakeStream(i) for i in ids]


class TestLocalSatisfies:
    def test_empty_local_not_satisfied(self):
        want = FakeStream(30280)
        assert _local_satisfies([], want, "audio") is False

    def test_audio_local_higher_satisfies(self):
        # 本地 192K(30280)>= 期望 132K(30232) → 满足
        want = FakeStream(30232)
        assert _local_satisfies([{"quality_id": 30280}], want, "audio") is True

    def test_audio_local_lower_not_satisfied(self):
        want = FakeStream(30280)
        assert _local_satisfies([{"quality_id": 30232}], want, "audio") is False

    def test_audio_table_not_numeric(self):
        # 本地杜比(30250)数值小于 Hi-Res(30251),但按顺序表杜比更高
        want = FakeStream(30251)
        assert _local_satisfies([{"quality_id": 30250}], want, "audio") is True

    def test_video_numeric(self):
        want = FakeStream(80)  # 1080P
        assert _local_satisfies([{"quality_id": 108}], want, "video") is True
        assert _local_satisfies([{"quality_id": 32}], want, "video") is False


class TestPickDesiredStream:
    def test_skip_sentinel(self):
        assert _pick_desired_stream(make_streams([30280]), -2, "audio") is None

    def test_auto_highest(self):
        s = _pick_desired_stream(make_streams([30216, 30232, 30280]), -1, "audio")
        assert s.quality_id == 30280

    def test_downgrade(self):
        # 期望 Hi-Res,曲目没有 → 降级到最高可用(192K)
        s = _pick_desired_stream(make_streams([30216, 30280]), 30251, "audio")
        assert s.quality_id == 30280

    def test_empty(self):
        assert _pick_desired_stream([], -1, "audio") is None
