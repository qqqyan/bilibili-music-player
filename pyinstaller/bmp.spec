# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置:onedir 目录包(解压即用)。

构建前置:web/dist 已生成(npm run build)。
用法:uv run pyinstaller pyinstaller/bmp.spec --noconfirm
"""

import os

from PyInstaller.utils.hooks import collect_all, collect_submodules

# spec 内相对路径以项目根(cwd)为准;构建脚本固定从项目根运行
PROJECT_ROOT = os.path.abspath(".")

datas = [
    (os.path.join(PROJECT_ROOT, "web", "dist"), os.path.join("web", "dist")),
]
binaries = []
hiddenimports = [
    # uvicorn 的插件式模块是动态导入,PyInstaller 静态分析不到
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.loops.asyncio",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
    "uvicorn.lifespan.off",
]

# curl_cffi:自带原生 libcurl 动态库,用 collect_all 完整收集(含二进制与数据)
for _pkg in ["curl_cffi"]:
    _d, _b, _h = collect_all(_pkg)
    datas += _d
    binaries += _b
    hiddenimports += _h

# bilibili_api(zoku):clients 等按字符串动态导入,静态分析不到,全量子模块收集
hiddenimports += collect_submodules("bilibili_api")

a = Analysis(
    [os.path.join(PROJECT_ROOT, "pyinstaller", "launcher.py")],
    pathex=[os.path.join(PROJECT_ROOT, "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["pytest", "ruff", "coverage"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    exclude_binaries=True,
    name="bilibili-music-player",
    console=True,  # 控制台窗口显示运行日志,关闭即退出
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    name="bilibili-music-player",
)
