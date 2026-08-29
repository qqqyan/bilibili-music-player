"""档位域逻辑(唯一事实来源):音质/画质标签、顺序、期望档选择。

前后端与各业务模块(播放决策、下载队列、缓存扫描)统一依赖本模块,
不要再在别处复制档位顺序表或降级规则。
"""

# 音质标签(quality_id -> 展示名)
QUALITY_LABELS = {
    0: "标准",  # 音频区单档 / MP4 单文件
    30216: "64K",
    30232: "132K",
    30280: "192K",
    30251: "Hi-Res",
    30250: "杜比",
}

# 音质高低顺序(低 -> 高)。注意:数值大小与音质高低不完全一致
# (杜比 30250 > Hi-Res 30251),比较必须用此表。
QUALITY_ORDER = [0, 30216, 30232, 30280, 30251, 30250]

# 网易云音质档(quality_id=请求码率 br,低 -> 高)
NETEASE_QUALITY_ORDER = [128000, 192000, 320000, 999000]
NETEASE_QUALITY_LABELS = {
    128000: "标准", 192000: "较高", 320000: "极高", 999000: "无损",
}

# 视频画质标签(quality_id -> 展示名)
VIDEO_QUALITY_LABELS = {
    6: "240P", 16: "360P", 32: "480P", 64: "720P", 74: "720P60",
    80: "1080P", 112: "1080P+", 116: "1080P60", 120: "4K",
    125: "HDR", 126: "杜比", 127: "8K",
}


def quality_label(quality_id: int) -> str:
    return QUALITY_LABELS.get(quality_id, NETEASE_QUALITY_LABELS.get(quality_id, str(quality_id)))


def video_quality_label(quality_id: int) -> str:
    return VIDEO_QUALITY_LABELS.get(quality_id, str(quality_id))


def order_of(quality_id: int, kind: str) -> int:
    """档位在质量顺序中的位置(越大越好)。

    音质按 bilibili QUALITY_ORDER,未知 id 再查网易云档表(跨源比较仅
    发生在同一曲目内,单曲只有单一来源,互不干扰);视频画质直接数值。
    """
    if kind == "video":
        return quality_id
    if quality_id in QUALITY_ORDER:
        return QUALITY_ORDER.index(quality_id)
    if quality_id in NETEASE_QUALITY_ORDER:
        return len(QUALITY_ORDER) + NETEASE_QUALITY_ORDER.index(quality_id)
    return len(QUALITY_ORDER) + len(NETEASE_QUALITY_ORDER)


def pick_stream_by_quality(streams: list, desired_id: int, kind: str):
    """期望档选择(streams 需已按质量升序):

    - desired_id < 0:取最高档
    - 精确档存在:用之
    - 否则降级:不高于期望档的最好档
    """
    if not streams:
        return None
    if desired_id < 0:
        return streams[-1]
    for s in streams:
        if s.quality_id == desired_id:
            return s
    lower = [
        s for s in streams if order_of(s.quality_id, kind) <= order_of(desired_id, kind)
    ]
    return lower[-1] if lower else streams[0]
