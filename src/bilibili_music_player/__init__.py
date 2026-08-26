"""bilibili-music-player 入口。

启动后端服务:
    bilibili-music-player
或:
    uv run python -m bilibili_music_player
"""

import uvicorn


def main() -> None:
    uvicorn.run(
        "bilibili_music_player.main:app",
        host="127.0.0.1",
        port=8000,
        reload=False,
    )


if __name__ == "__main__":
    main()
