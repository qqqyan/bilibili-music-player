"""网易云音乐路由:扫码登录(QR 会话) + 登录态 + 搜索。

QR 流程(现行 web 端点,实测验证):
    POST /api/netease/qrcode 生成 unikey 并本地画 SVG 二维码
    前端 2s 轮询 status:scan(801)/confirm(802)/done(803)/expired(800)
    done 时后端从响应 Set-Cookie 提取 MUSIC_U 等保存为登录态。
"""

import time
import urllib.parse
import uuid

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from ..config import get_netease_cookie, refresh_netease_cookie
from ..models import SearchPage, TrackInfo
from ..repositories import netease_auth_store
from ..services import netease
from ..services._utils import abs_url

router = APIRouter(prefix="/api/netease")


class CookieRequest(BaseModel):
    cookie: str

# 二维码会话:session_id -> {"qr": QrSession, "created_at"}
_qr_sessions: dict[str, dict] = {}
_QR_TTL = 300  # 二维码有效期(官方约 5 分钟)


def _purge_expired() -> None:
    now = time.time()
    for sid in [s for s, v in _qr_sessions.items() if now - v["created_at"] > _QR_TTL]:
        v["qr"].client.close()
        _qr_sessions.pop(sid, None)


def _song_to_track(s: dict) -> TrackInfo:
    """网易云歌曲条目 → TrackInfo(兼容新旧两套字段名)。"""
    artists = [a["name"] for a in (s.get("artists") or s.get("ar") or []) if a.get("name")]
    album = (s.get("album") or s.get("al") or {}).get("name") or ""
    cover = (s.get("album") or s.get("al") or {}).get("picUrl") or ""
    duration = s.get("dt") or s.get("duration") or 0
    return TrackInfo(
        id=f"ne{s['id']}",
        title=s.get("name") or "",
        artist="、".join(artists) or "未知歌手",
        mid=0,
        cover=abs_url(cover),
        duration=round(duration / 1000),
        source="网易云音乐",
        album=album,
    )


@router.post("/qrcode")
async def api_qrcode():
    """生成扫码登录二维码(SVG data URL)。"""
    _purge_expired()
    qr = netease.QrSession()
    try:
        unikey = qr.create_qr()
        svg = netease.qr_svg(unikey)
    except ValueError as e:
        qr.client.close()
        raise HTTPException(status_code=502, detail=str(e))
    sid = uuid.uuid4().hex
    _qr_sessions[sid] = {"qr": qr, "created_at": time.time()}
    return {
        "session_id": sid,
        "image_data_url": "data:image/svg+xml;utf8," + urllib.parse.quote(svg),
        "expires_in": _QR_TTL,
    }


@router.get("/qrcode/status/{session_id}")
async def api_qrcode_status(session_id: str):
    """轮询扫码状态(会话内轮询,保证最终 MUSIC_U 发放同源)。"""
    sess = _qr_sessions.get(session_id)
    if sess is None:
        raise HTTPException(status_code=404, detail="二维码会话不存在或已过期")
    qr: netease.QrSession = sess["qr"]
    try:
        status, data, cookie = qr.poll()
    except ValueError as e:
        raise HTTPException(status_code=502, detail=str(e))
    print(f"[netease-qr] {session_id[:8]} status={status}", flush=True)
    if status == "done":
        if not cookie:
            qr.client.close()
            _qr_sessions.pop(session_id, None)
            raise HTTPException(status_code=502, detail="登录成功但未获取到凭证,请重试")
        user: dict = {}
        try:
            user = netease.user_detail(cookie)
        except Exception:
            pass  # 用户信息拉取失败不阻断登录
        netease_auth_store.save_auth(cookie, user)
        netease.save_env_seed(cookie)  # 环境 cookie 自保鲜
        refresh_netease_cookie()
        qr.client.close()
        _qr_sessions.pop(session_id, None)
        return {"status": "done", "user": user}
    if status == "expired":
        qr.client.close()
        _qr_sessions.pop(session_id, None)
        return {"status": "expired"}
    if status == "confirm":
        return {"status": "confirm", "user": {"name": data.get("nickname") or ""}}
    return {"status": "scan"}


@router.get("/status")
async def api_status():
    """登录状态(昵称/头像)。"""
    cookie = get_netease_cookie()
    if not cookie:
        return {"logged_in": False, "user": None}
    record = netease_auth_store.load_auth()
    return {"logged_in": True, "user": (record or {}).get("user") or {}}


@router.post("/cookie")
async def api_cookie(req: CookieRequest):
    """手动导入浏览器 cookie 登录(跨设备通用:每台设备用自己浏览器的凭证)。"""
    user = netease.cookie_user(req.cookie)
    if user is None:
        raise HTTPException(
            status_code=400, detail="cookie 无效(MUSIC_U 缺失或已过期)"
        )
    netease_auth_store.save_auth(req.cookie, user)
    netease.save_env_seed(req.cookie)
    refresh_netease_cookie()
    return {"logged_in": True, "user": user}


@router.post("/logout")
async def api_logout():
    netease_auth_store.clear_auth()
    refresh_netease_cookie()
    return {"logged_out": True}


@router.get("/search", response_model=SearchPage)
async def api_search(
    keyword: str = Query(..., min_length=1, description="搜索关键词"),
    page: int = Query(1, ge=1),
):
    """搜索网易云歌曲(匿名可用;登录后 VIP 曲目可播)。"""
    try:
        songs, total = netease.search(keyword, page, get_netease_cookie())
        # 搜索条目缺专辑封面,批量补详情(带封面)
        songs = netease.enrich_songs(songs, get_netease_cookie())
    except ValueError as e:
        raise HTTPException(status_code=502, detail=str(e))
    items = [_song_to_track(s) for s in songs]
    return SearchPage(items=items, has_more=(page - 1) * 20 + len(songs) < total)


@router.get("/artists")
async def api_artists(
    keyword: str = Query(..., min_length=1, description="搜索关键词"),
):
    """搜索网易云歌手(与 bilibili UP 主卡片对齐的字段)。"""
    try:
        artists = netease.search_artists(keyword, get_netease_cookie())
    except ValueError as e:
        raise HTTPException(status_code=502, detail=str(e))
    items = [
        {
            "mid": a.get("id") or 0,
            "name": a.get("name") or "",
            "face": abs_url(a.get("picUrl") or a.get("img1v1Url") or ""),
            # fansSize 部分歌手有真实粉丝数;没有时前端回退显示作品数
            "fans": a.get("fansSize") or 0,
            "songs": a.get("musicSize") or 0,
        }
        for a in artists
    ]
    return {"items": items}


@router.get("/artist/{artist_id}")
async def api_artist(artist_id: int):
    """歌手主页:信息 + 热门歌曲(结构对齐 /api/user/{mid})。"""
    try:
        info = netease.artist_detail(artist_id, get_netease_cookie())
        songs = netease.artist_songs(artist_id, get_netease_cookie())
    except ValueError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return {
        "user": {
            "mid": artist_id,
            "name": info.get("name") or "未知歌手",
            "face": abs_url(info.get("picUrl") or info.get("img1v1Url") or ""),
            "sign": info.get("briefDesc") or "",
            "fans": info.get("fansSize") or 0,
            "songs": info.get("musicSize") or 0,
            "albums": info.get("albumSize") or 0,
        },
        "videos": [_song_to_track(s) for s in songs],
        "has_more": False,
    }
