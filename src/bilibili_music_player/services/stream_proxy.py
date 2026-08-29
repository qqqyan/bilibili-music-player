"""CDN 流代理。

浏览器 <audio>/<video> 无法自定义请求头,而 B 站 CDN 要求
Referer + 浏览器 UA,故由后端代理转发。支持:
  - Range 透传(拖动进度条)
  - 多候选 CDN 依次回退(播放策略之一)
"""

import uuid
from dataclasses import dataclass, field

import httpx
from fastapi import HTTPException

BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
REFERER = "https://www.bilibili.com/"


@dataclass
class StreamEntry:
    urls: list[str]  # 主 CDN + 备用 CDN,依次尝试
    headers: dict[str, str] = field(
        default_factory=lambda: {
            "User-Agent": BROWSER_UA,
            "Referer": REFERER,  # B 站 CDN 必须带 Referer,否则 403
        }
    )
    mime: str | None = None  # 非空时覆盖上游 content-type(如网易云 CDN 统一标 audio/mpeg)


# token -> StreamEntry(进程内存即可,重启失效不影响使用)
_STREAMS: dict[str, StreamEntry] = {}


def register_stream(
    urls: list[str],
    headers: dict[str, str] | None = None,
    mime: str | None = None,
) -> str:
    """注册一组候选流 URL,返回代理 token。

    headers 缺省为 bilibili UA/Referer;其他来源(如网易云)可自定。
    mime 非空时转发生效时覆盖上游 content-type。
    """
    token = uuid.uuid4().hex
    # headers 缺省走 StreamEntry 默认(bilibili UA/Referer);显式传入才覆盖
    _STREAMS[token] = (
        StreamEntry(urls=urls)
        if not headers and not mime
        else StreamEntry(urls=urls, headers=headers or {}, mime=mime)
    )
    return token


def stream_token_url(token: str) -> str:
    return f"/api/stream/{token}"


def get_stream_urls(token: str) -> list[str]:
    """按 token 取回真实 CDN URL 列表(供下载器等内部组件使用)。"""
    entry = _STREAMS.get(token)
    return list(entry.urls) if entry else []


def get_stream_headers(token: str) -> dict[str, str]:
    """按 token 取回请求头(下载器按来源携带正确 Referer/UA)。"""
    entry = _STREAMS.get(token)
    return dict(entry.headers) if entry else {}


async def prepare_stream(token: str, range_header: str | None):
    """依次尝试候选 CDN,返回 (状态码, 响应头, body 生成器)。

    body 迭代结束时自动关闭底层连接。
    """
    entry = _STREAMS.get(token)
    if entry is None:
        raise HTTPException(status_code=404, detail="流不存在或已过期")

    # read 超时置空:流式传输期间允许长时间无数据到达的间隙
    client = httpx.AsyncClient(
        timeout=httpx.Timeout(connect=10.0, read=None, write=None, pool=None),
        follow_redirects=True,
    )
    last_error: Exception | None = None
    for url in entry.urls:
        headers = {**entry.headers}
        if range_header:
            headers["Range"] = range_header
        try:
            req = client.build_request("GET", url, headers=headers)
            resp = await client.send(req, stream=True)
        except httpx.HTTPError as e:
            last_error = e
            continue
        if resp.status_code not in (200, 206):
            last_error = HTTPException(resp.status_code, f"CDN 返回 {resp.status_code}")
            await resp.aclose()
            continue

        resp_headers = {
            "Content-Type": entry.mime
            or resp.headers.get("content-type", "application/octet-stream"),
            "Accept-Ranges": "bytes",
            "Cache-Control": "no-store",
        }
        for key in ("content-length", "content-range"):
            if key in resp.headers:
                resp_headers[key.title()] = resp.headers[key]

        async def body():
            try:
                async for chunk in resp.aiter_bytes():
                    yield chunk
            finally:
                await resp.aclose()
                await client.aclose()

        return resp.status_code, resp_headers, body()

    await client.aclose()
    if last_error is not None:
        raise HTTPException(status_code=502, detail=f"所有候选 CDN 均不可用: {last_error}")
    raise HTTPException(status_code=502, detail="没有可用的 CDN 地址")
