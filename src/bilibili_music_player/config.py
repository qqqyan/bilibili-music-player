"""配置加载:登录凭证(可选)。

凭证通过环境变量或项目根目录的 .env 文件提供:
  BILI_SESSDATA / BILI_BILI_JCT / BILI_BUVID3 / BILI_BUVID4 / BILI_DEDEUSERID

不配置也可运行(匿名),但登录后可获取更高音质(192K / Hi-Res / 杜比)。
"""

import os
from functools import lru_cache
from pathlib import Path

from bilibili_api.utils.network import Credential

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def _load_dotenv(path: Path | None = None) -> None:
    """极简 .env 解析:KEY=VALUE 行,# 开头为注释。"""
    env_file = path or (PROJECT_ROOT / ".env")
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@lru_cache(maxsize=1)
def get_credential() -> Credential:
    """构建 Credential,未配置登录态时为空凭证(匿名访问)。"""
    _load_dotenv()
    return Credential(
        sessdata=os.environ.get("BILI_SESSDATA", ""),
        bili_jct=os.environ.get("BILI_BILI_JCT", ""),
        buvid3=os.environ.get("BILI_BUVID3", ""),
        buvid4=os.environ.get("BILI_BUVID4", ""),
        dedeuserid=os.environ.get("BILI_DEDEUSERID", ""),
    )


def is_logged_in() -> bool:
    return bool(get_credential().sessdata)


def configure_client(impersonate: str = "chrome") -> None:
    """为 zoku 的 curl_cffi 客户端开启浏览器伪装(需在事件循环内调用)。

    zoku 按 curl_cffi > aiohttp > httpx 的优先级选择客户端,默认已选 curl_cffi,
    但 impersonate 默认为空。开启后由伪装浏览器的 TLS 指纹/UA 发起请求,
    降低被 B 站风控的概率(库内部会自动处理 UA 冲突)。
    """
    from bilibili_api.utils.network import get_client

    client = get_client()
    if hasattr(client, "set_impersonate"):
        client.set_impersonate(impersonate)
        print(f"[config] curl_cffi impersonate 已开启: {impersonate}", flush=True)
    else:
        print("[config] 当前客户端不支持 impersonate,跳过", flush=True)
