"""档位域规则测试(quality.py 是唯一事实来源,前后端与各服务都依赖它)。"""

from bilibili_music_player.quality import (
    QUALITY_ORDER,
    order_of,
    pick_stream_by_quality,
    quality_label,
    video_quality_label,
)


class FakeStream:
    def __init__(self, quality_id):
        self.quality_id = quality_id


def make_streams(ids):
    return [FakeStream(i) for i in ids]


class TestOrderOf:
    def test_audio_order_uses_table_not_numeric(self):
        # 数值上 30250(杜比) < 30251(Hi-Res),但音质顺序杜比更高
        assert order_of(30250, "audio") > order_of(30251, "audio")

    def test_audio_order_increasing(self):
        for a, b in zip(QUALITY_ORDER, QUALITY_ORDER[1:]):
            assert order_of(a, "audio") < order_of(b, "audio")

    def test_video_order_numeric(self):
        assert order_of(80, "video") > order_of(32, "video")
        assert order_of(127, "video") > order_of(120, "video")

    def test_unknown_audio_id_goes_last(self):
        assert order_of(999999, "audio") > order_of(30250, "audio")


class TestPickStreamByQuality:
    def test_auto_picks_highest(self):
        streams = make_streams([30216, 30232, 30280])
        assert pick_stream_by_quality(streams, -1, "audio").quality_id == 30280

    def test_exact_match(self):
        streams = make_streams([30216, 30232, 30280])
        assert pick_stream_by_quality(streams, 30232, "audio").quality_id == 30232

    def test_downgrade_to_best_available(self):
        # 期望 Hi-Res(30251),曲目最高只有 192K(30280) → 降级到 192K
        streams = make_streams([30216, 30232, 30280])
        assert pick_stream_by_quality(streams, 30251, "audio").quality_id == 30280

    def test_video_downgrade(self):
        # 期望 1080P(80),曲目最高 720P(64) → 降级到 720P
        streams = make_streams([16, 32, 64])
        assert pick_stream_by_quality(streams, 80, "video").quality_id == 64

    def test_empty_returns_none(self):
        assert pick_stream_by_quality([], -1, "audio") is None


class TestLabels:
    def test_audio_labels(self):
        assert quality_label(30280) == "192K"
        assert quality_label(30251) == "Hi-Res"

    def test_video_labels(self):
        assert video_quality_label(80) == "1080P"
        assert video_quality_label(32) == "480P"
