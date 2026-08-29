"""API 数据模型。"""

from pydantic import BaseModel


class TrackInfo(BaseModel):
    """一条曲目的元数据(搜索结果条目,也是播放列表条目)。

    当前所有曲目均为 bilibili 视频(id 形如 bvBVxxx),模型收敛为单一形态;
    匹配来源的曲目额外携带 orig_* 字段(替换歌曲用),占位曲目 id 形如 match:123。
    """

    id: str  # bvBVxxx / match:123(占位)
    title: str
    artist: str  # UP 主
    mid: int = 0  # UP 主 ID(0 = 未知;悬停预览/进入主页用)
    cover: str  # 封面 URL
    duration: int  # 时长(秒)
    source: str  # 来源标签,如 "bilibili 视频"
    album: str = ""  # 专辑名(网易云搜索结果展示;bilibili 曲目为空)
    orig_name: str = ""  # 原平台歌名(匹配来源/首次替换前的快照,替换歌曲搜索用)
    orig_artists: list[str] = []  # 原平台歌手
    match_netease_id: int = 0  # 匹配任务歌曲 ID(0 = 非匹配来源)


class StreamInfo(BaseModel):
    """一条可播放的流(代理地址,已带 token)。"""

    quality_id: int  # 音质枚举值(AudioQuality.value),音频区固定为 0
    quality: str  # 音质标签,如 "标准" / "64K" / "192K" / "Hi-Res"
    mime: str  # MIME 类型,如 audio/mp4
    bandwidth: int  # 码率 bps(未知为 0)
    stream_url: str  # /api/stream/{token}


class ResolvedTrack(TrackInfo):
    """解析后的曲目:元数据 + 音频音质档 + 视频画质档(两者对称,均为 peer)。

    音频/视频档位均按质量从低到高排列;无画面的视频 video_streams 为空。
    """

    audio_streams: list[StreamInfo]  # 音频档位,按音质从低到高
    video_streams: list[StreamInfo] = []  # 视频档位,按画质从低到高(无画面时为空)


class SearchPage(BaseModel):
    items: list[TrackInfo]
    has_more: bool
