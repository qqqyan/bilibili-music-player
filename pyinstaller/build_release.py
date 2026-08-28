"""一键构建 release 包:前端构建 + PyInstaller onedir + 压缩归档。

用法(项目根):
    uv run python pyinstaller/build_release.py
    # 前端已构建好时:
    uv run python pyinstaller/build_release.py --skip-frontend

产物(按运行平台自动命名):
    dist_release/bilibili-music-player-0.1.0-windows.zip
    dist_release/bilibili-music-player-0.1.0-macos-arm64.tar.gz
    dist_release/bilibili-music-player-0.1.0-linux-x86_64.tar.gz

用户拿到后解压,双击 bilibili-music-player(.exe) 即可,无需安装 Python。
"""

import argparse
import platform
import shutil
import subprocess
import sys
from importlib.metadata import version
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist_release"
WORK = ROOT / "build_tmp"
VERSION = version("bilibili-music-player")


def run(cmd: list, cwd: Path | None = None) -> None:
    print("+", " ".join(map(str, cmd)), flush=True)
    subprocess.run([str(c) for c in cmd], check=True, cwd=cwd or ROOT)


def platform_tag() -> str:
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform.startswith("darwin"):
        return f"macos-{platform.machine().lower()}"
    return f"linux-{platform.machine().lower()}"


def main() -> None:
    parser = argparse.ArgumentParser(description="构建 release 包")
    parser.add_argument(
        "--skip-frontend", action="store_true", help="web/dist 已构建时跳过前端构建"
    )
    args = parser.parse_args()

    if not args.skip_frontend:
        run(["npm", "run", "build"], cwd=ROOT / "web")
    if not (ROOT / "web" / "dist" / "index.html").exists():
        sys.exit("web/dist 不存在,请先在 web/ 目录 npm run build")

    if DIST.exists():
        shutil.rmtree(DIST)
    if WORK.exists():
        shutil.rmtree(WORK)

    run(
        [
            "uv", "run", "pyinstaller", "pyinstaller/bmp.spec",
            "--noconfirm", "--distpath", str(DIST), "--workpath", str(WORK),
        ]
    )

    tag = platform_tag()
    base = DIST / f"bilibili-music-player-{VERSION}-{tag}"
    if sys.platform.startswith("win"):
        shutil.make_archive(str(base), "zip", root_dir=DIST, base_dir="bilibili-music-player")
        print(f"\n完成: {base}.zip")
    else:
        shutil.make_archive(str(base), "gztar", root_dir=DIST, base_dir="bilibili-music-player")
        print(f"\n完成: {base}.tar.gz")


if __name__ == "__main__":
    main()
