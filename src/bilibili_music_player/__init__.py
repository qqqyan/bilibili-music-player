"""bilibili-music-player 入口。

启动后端服务:
    bilibili-music-player
或:
    uv run python -m bilibili_music_player
"""

import os
import sys
import threading
import webbrowser

import uvicorn

# 端口:默认 8000,可用环境变量 BMP_PORT 覆盖(打包版友好提示用)
_PORT = int(os.environ.get("BMP_PORT", "8000"))


def main() -> None:
    # 打包版:延迟 1.5s 自动打开浏览器(等服务就绪),并打印友好提示
    if getattr(sys, "frozen", False):
        url = f"http://127.0.0.1:{_PORT}"
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
        print(f"bilibili 音乐播放器已启动: {url}")
        print("关闭本窗口即退出服务。")
    uvicorn.run(
        "bilibili_music_player.app:app",
        host="127.0.0.1",
        port=_PORT,
        reload=False,
    )


if __name__ == "__main__":
    main()
