"""服务入口:uvicorn 启动。

应用组装见 app.py;路由见 routers/。
"""

from .app import app

__all__ = ["app"]
