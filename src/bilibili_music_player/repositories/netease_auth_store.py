"""网易云登录态持久化:data/netease_auth.json(cookie 串 + 用户信息)。"""

import json

from ..config import PROJECT_ROOT

DATA_DIR = PROJECT_ROOT / "data"
AUTH_FILE = DATA_DIR / "netease_auth.json"


def load_auth() -> dict | None:
    """读取网易云登录记录;缺失/损坏返回 None。"""
    if not AUTH_FILE.exists():
        return None
    try:
        data = json.loads(AUTH_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, OSError):
        return None


def save_auth(cookie: str, user: dict | None = None) -> dict:
    """保存登录记录(覆盖式),返回记录。"""
    record = {"cookie": cookie, "user": user or {}}
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    AUTH_FILE.write_text(
        json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return record


def clear_auth() -> None:
    AUTH_FILE.unlink(missing_ok=True)


def cookie_from_record(record: dict) -> str:
    return (record or {}).get("cookie") or ""
