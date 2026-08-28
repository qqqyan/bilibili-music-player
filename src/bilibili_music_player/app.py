"""FastAPI 应用组装:lifespan、中间件、路由注册。

分层(借鉴 Spring Boot 思路):
  routers/     Controller 层:参数解析与响应组装
  bilibili_client / download_manager / stream_proxy  Service 层:业务逻辑
  *_store.py   Repository 层:持久化
  quality.py / models.py  Domain 层:档位规则与数据模型
"""

import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .config import configure_client, is_logged_in
from .services.download_manager import manager as download_manager
from .routers import auth, cache, playlist, search, settings, track, user


@asynccontextmanager
async def lifespan(_: FastAPI):
    # 事件循环内初始化 zoku 客户端:开启 curl_cffi 浏览器伪装
    configure_client()
    # 预热 zoku 全局状态(wbi mixin key / buvid 等):它们「首次用到才获取」
    # 且无并发保护,启动时单线程预热可消除并发首次获取的竞态窗口
    try:
        from bilibili_api.utils.network import get_buvid, get_wbi_mixin_key

        await get_wbi_mixin_key()
        await get_buvid()
        print("[config] zoku 全局状态预热完成(wbi/buvid)", flush=True)
    except Exception as e:
        print(f"[config] 预热失败(不影响使用,重试机制兜底): {str(e)[:120]}", flush=True)
    await download_manager.start()
    # 已登录时启动检查凭证有效性,过期自动续期
    if is_logged_in():
        await auth.try_refresh_credential()
    yield
    await download_manager.stop()


app = FastAPI(title="bilibili-music-player", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 路由注册(按域)
app.include_router(search.router)
app.include_router(track.router)
app.include_router(user.router)
app.include_router(cache.router)
app.include_router(playlist.router)
app.include_router(settings.router)
app.include_router(auth.router)


@app.get("/api/health")
async def health():
    return {"status": "ok"}


# 前端构建产物(web/dist 存在时由后端直接托管)
# PyInstaller 打包后资源在 _MEIPASS(onedir 的 _internal)内
if getattr(sys, "frozen", False):
    _DIST = Path(sys._MEIPASS) / "web" / "dist"
else:
    _DIST = Path(__file__).resolve().parent.parent.parent / "web" / "dist"
if _DIST.exists():
    app.mount("/", StaticFiles(directory=_DIST, html=True), name="web")
