"""服务层共享小工具(URL 补全、标题清洗、时长解析、字段取值)。"""

import re


def abs_url(url: str) -> str:
    """补全协议头(B 站接口常返回 //host/path)。"""
    if not url:
        return ""
    return url if url.startswith("http") else f"https:{url}"


def strip_em(text: str) -> str:
    """去掉搜索结果标题里的 <em class="keyword"> 高亮标签。"""
    return re.sub(r"</?em[^>]*>", "", text or "")


def parse_duration(value) -> int:
    """时长归一化为秒:支持 "mm:ss" / "hh:mm:ss" / 数字秒。"""
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str) and ":" in value:
        parts = [int(p) for p in value.split(":")]
        secs = 0
        for p in parts:
            secs = secs * 60 + p
        return secs
    return 0


def first(data: dict, *keys, default=""):
    """按候选键名依次取值。"""
    for key in keys:
        if data.get(key) not in (None, ""):
            return data[key]
    return default
