"""测试夹具:无 lifespan 的测试应用(不触发网络初始化)。"""

import pytest
from fastapi import FastAPI

from bilibili_music_player.routers import auth, cache, match, playlist, search, settings, track


@pytest.fixture()
def test_app():
    """组装所有路由的 FastAPI 实例(不跑 lifespan,避免网络依赖)。"""
    app = FastAPI()
    app.include_router(search.router)
    app.include_router(track.router)
    app.include_router(cache.router)
    app.include_router(playlist.router)
    app.include_router(settings.router)
    app.include_router(auth.router)
    app.include_router(match.router)

    @app.get("/api/health")
    async def health():
        return {"status": "ok"}

    return app
