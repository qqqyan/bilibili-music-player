"""登录凭证持久化:data/auth.json。

前端二维码/手动登录成功后写入;后端启动时优先加载(高于 .env)。
"""

import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent.parent.parent / "data"
AUTH_FILE = DATA_DIR / "auth.json"

_CREDENTIAL_KEYS = ("sessdata", "bili_jct", "dedeuserid", "ac_time_value", "buvid3", "buvid4")


def load_auth() -> dict | None:
    """读取已保存的登录凭证与用户信息(不存在/损坏返回 None)。"""
    if not AUTH_FILE.exists():
        return None
    try:
        return json.loads(AUTH_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def save_auth(credential_fields: dict, user: dict | None = None) -> dict:
    """保存凭证字段与用户信息,返回完整记录。"""
    record = {
        "credentials": {
            key: credential_fields.get(key, "") for key in _CREDENTIAL_KEYS
        },
        "user": user,
    }
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    AUTH_FILE.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return record


def clear_auth() -> None:
    AUTH_FILE.unlink(missing_ok=True)


def credentials_from_record(record: dict | None) -> dict:
    """从记录中提取凭证字段(供 Credential 构造)。"""
    if not record:
        return {}
    return {key: record.get("credentials", {}).get(key, "") for key in _CREDENTIAL_KEYS}
