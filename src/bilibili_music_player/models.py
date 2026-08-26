"""API 数据模型。"""

from pydantic import BaseModel


class TrackInfo(BaseModel):
    """一条曲目/视频的元数据(搜索结果条目,也是播放列表条目)。"""

    id: str  # 内部 ID:音频区为 au{auid},视频为 bv{bvid}
    kind: str  # "audio"(音频区歌曲) | "video"(视频)
    title: str
    artist: str  # UP 主
    cover: str  # 封面 URL
    duration: int  # 时长(秒)
    source: str  # 来源标签,如 "bilibili 音频区" / "bilibili 视频"


class StreamInfo(BaseModel):
    """一条可播放的流(代理地址,已带 token)。"""

    quality_id: int  # 音质枚举值(AudioQuality.value),音频区固定为 0
    quality: str  # 音质标签,如 "标准" / "64K" / "192K" / "Hi-Res"
    mime: str  # MIME 类型,如 audio/mp4
    bandwidth: int  # 码率 bps(未知为 0)
    stream_url: str  # /api/stream/{token}


class ResolvedTrack(TrackInfo):
    """解析后的曲目:元数据 + 音频音质档 + 视频画质档(两者对称,均为 peer)。

    音频/视频档位均按质量从低到高排列;视频条目才可能有 video_streams。
    """

    audio_streams: list[StreamInfo]  # 音频档位,按音质从低到高
    video_streams: list[StreamInfo] = []  # 视频档位,按画质从低到高(无画面时为空)


class SearchPage(BaseModel):
    items: list[TrackInfo]
    has_more: bool
