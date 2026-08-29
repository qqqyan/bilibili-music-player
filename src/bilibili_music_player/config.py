"""配置加载:登录凭证(可选)。

凭证通过环境变量或项目根目录的 .env 文件提供:
  BILI_SESSDATA / BILI_BILI_JCT / BILI_BUVID3 / BILI_BUVID4 / BILI_DEDEUSERID

不配置也可运行(匿名),但登录后可获取更高音质(192K / Hi-Res / 杜比)。
"""

import os
import sys
from pathlib import Path

from bilibili_api.utils.network import Credential

# PyInstaller onedir 打包:exe 所在目录(用户解压目录)即应用根,data/ 建在其旁
if getattr(sys, "frozen", False):
    PROJECT_ROOT = Path(sys.executable).resolve().parent
else:
    PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

from .repositories import auth_store, netease_auth_store


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


_credential_cache: Credential | None = None


def get_credential() -> Credential:
    """当前生效的 Credential(内存缓存,登录/登出后热更新)。

    优先级:data/auth.json(前端登录) > .env(手动配置) > 匿名空凭证。
    """
    global _credential_cache
    if _credential_cache is None:
        _credential_cache = _build_credential()
    return _credential_cache


def refresh_credential() -> Credential:
    """登录态变更后重建凭证并清除缓存。"""
    global _credential_cache
    _credential_cache = None
    return get_credential()


def _build_credential() -> Credential:
    _load_dotenv()
    record = auth_store.load_auth()
    if record:
        fields = auth_store.credentials_from_record(record)
        return Credential(**fields)
    return Credential(
        sessdata=os.environ.get("BILI_SESSDATA", ""),
        bili_jct=os.environ.get("BILI_BILI_JCT", ""),
        buvid3=os.environ.get("BILI_BUVID3", ""),
        buvid4=os.environ.get("BILI_BUVID4", ""),
        dedeuserid=os.environ.get("BILI_DEDEUSERID", ""),
    )


def is_logged_in() -> bool:
    return bool(get_credential().sessdata)


# ---------------------------------------------------------------- 网易云

_netease_cookie_cache: str | None = None
_netease_cookie_loaded = False


def get_netease_cookie() -> str:
    """当前网易云登录 cookie(MUSIC_U 等,内存缓存,登录/登出后热更新)。"""
    global _netease_cookie_cache, _netease_cookie_loaded
    if not _netease_cookie_loaded:
        _netease_cookie_cache = netease_auth_store.cookie_from_record(
            netease_auth_store.load_auth() or {}
        )
        _netease_cookie_loaded = True
    return _netease_cookie_cache or ""


def refresh_netease_cookie() -> str:
    """登录态变更后重建缓存并返回当前 cookie。"""
    global _netease_cookie_cache, _netease_cookie_loaded
    _netease_cookie_cache = None
    _netease_cookie_loaded = False
    return get_netease_cookie()


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
