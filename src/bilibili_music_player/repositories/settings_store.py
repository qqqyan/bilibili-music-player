"""应用设置持久化:data/settings.json。"""

import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent.parent.parent / "data"
SETTINGS_FILE = DATA_DIR / "settings.json"

DEFAULTS: dict = {
    # 下载完成更高档后,自动删除同类型更低档的本地缓存
    "cleanup_old_quality": False,
}


def load_settings() -> dict:
    """读取设置(与默认值合并,缺失字段用默认)。"""
    settings = dict(DEFAULTS)
    if SETTINGS_FILE.exists():
        try:
            saved = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            if isinstance(saved, dict):
                settings.update(saved)
        except (json.JSONDecodeError, OSError):
            pass
    return settings


def save_settings(patch: dict) -> dict:
    """合并保存设置,返回完整设置。"""
    settings = load_settings()
    settings.update(patch)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(
        json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return settings
