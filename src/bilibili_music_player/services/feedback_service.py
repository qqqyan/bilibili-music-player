"""应用内反馈:脱敏日志收集、GitHub issue 预填与本地诊断包。

流程(无远程服务器,零配置):
  前端点「反馈问题」→ 描述 + 截图 → POST /api/feedback/report
  → 汇总后端最近日志(print / logging / uvicorn)与前端日志、环境信息
  → 统一脱敏后生成 GitHub issue 预填链接(在浏览器里由用户确认提交)
  → 同时把截图、完整日志、报告保存到 data/feedback/<时间戳>/,
     截图可直接粘贴进 issue,完整日志可拖入 issue 或留档。

脱敏是外发前的最后一道关口:登录凭证、Cookie、token、用户主目录路径等
一律替换为 ***;完整(未截断)日志只落在本地诊断包。
"""

from __future__ import annotations

import base64
import json
import logging
import os
import platform
import re
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from ..config import PROJECT_ROOT

# ---------------------------------------------------------------- 常量

GITHUB_REPO = "qqqyan/bilibili-music-player"
GITHUB_REPO_URL = f"https://github.com/{GITHUB_REPO}"
GITHUB_NEW_ISSUE = f"{GITHUB_REPO_URL}/issues/new"

# GitHub 预填 issue 的 URL 长度上限(官方限制 8192,留出余量)
MAX_ISSUE_URL = 7800
# 用户描述 / 标题的输入上限(超过 URL 预算时会再裁剪外发部分)
MAX_DESCRIPTION = 20000
MAX_TITLE = 120
MAX_SCREENSHOT_BYTES = 15 * 1024 * 1024
KEEP_BUNDLES = 20

_LOG_MAX_LINES = 400
_LOG_MAX_CHARS = 200_000
_LOG_LINE_CHARS = 1500

_DATA_URL_RE = re.compile(
    r"^data:image/(?P<fmt>png|jpeg|jpg|webp);base64,(?P<data>[A-Za-z0-9+/=\s]+)$",
    re.IGNORECASE | re.DOTALL,
)
_IMAGE_EXTS = {"png": "png", "jpeg": "jpg", "jpg": "jpg", "webp": "webp"}

# ---------------------------------------------------------------- 日志缓冲

_logs: list[str] = []
_log_chars = 0
_log_lock = threading.Lock()


def record_log(line: str) -> None:
    """写入一行日志(供 stdout/stderr tee 与 logging handler 调用)。"""
    global _log_chars
    line = str(line).replace("\x00", "").rstrip()
    if not line.strip():
        return
    if len(line) > _LOG_LINE_CHARS:
        line = line[:_LOG_LINE_CHARS] + "…"
    entry = f"[{time.strftime('%H:%M:%S')}] {line}"
    with _log_lock:
        _logs.append(entry)
        _log_chars += len(entry)
        while _logs and (len(_logs) > _LOG_MAX_LINES or _log_chars > _LOG_MAX_CHARS):
            _log_chars -= len(_logs.pop(0))


def record_output(data: str) -> None:
    """按行写入一段输出(tee 用;支持一次写入多行)。"""
    if not data:
        return
    for line in str(data).splitlines():
        record_log(line)


def log_count() -> int:
    with _log_lock:
        return len(_logs)


def recent_logs(limit: int = 200) -> list[str]:
    """最近的日志(已脱敏)。"""
    with _log_lock:
        lines = list(_logs)[-limit:]
    return [redact(line) for line in lines]


def clear_logs() -> None:
    """清空日志缓冲(测试用)。"""
    global _log_chars
    with _log_lock:
        _logs.clear()
        _log_chars = 0


class _Tee:
    """把 stdout/stderr 原样转发,同时按行收集到环形缓冲。"""

    def __init__(self, stream):
        self._stream = stream
        self._buf = ""
        self._buf_lock = threading.Lock()

    def write(self, data):
        try:
            self._stream.write(data)
        except Exception:  # 控制台编码等异常不应影响应用
            pass
        if data:
            with self._buf_lock:
                self._buf += str(data)
                while "\n" in self._buf:
                    line, self._buf = self._buf.split("\n", 1)
                    record_log(line)
                if len(self._buf) > _LOG_LINE_CHARS * 2:
                    record_log(self._buf)
                    self._buf = ""
        return len(data)

    def flush(self):
        try:
            self._stream.flush()
        except Exception:
            pass

    def __getattr__(self, name):
        return getattr(self._stream, name)


class _LoggingBufferHandler(logging.Handler):
    def emit(self, record):
        try:
            message = self.format(record)
        except Exception:
            message = record.getMessage()
        record_output(str(message))


_LOGGING_HANDLER = _LoggingBufferHandler()
_LOGGING_HANDLER.setFormatter(logging.Formatter("[%(name)s] %(message)s"))
_capture_installed = False


def install_log_capture() -> None:
    """接管 stdout/stderr 与标准 logging(幂等)。

    应用大量使用 print 输出运行日志,包裹流比逐处改成 logging 改动小;
    uvicorn 的 logging handler 持有原始流引用,所以额外挂到
    uvicorn / uvicorn.access logger 上,访问日志与异常也能进缓冲。
    """
    global _capture_installed
    if _capture_installed:
        return
    if sys.stdout is not None:
        sys.stdout = _Tee(sys.stdout)
    if sys.stderr is not None:
        sys.stderr = _Tee(sys.stderr)
    logging.getLogger().addHandler(_LOGGING_HANDLER)
    # uvicorn 的 logger 在配置后 propagate=False,分别挂载避免漏采/重复
    for name in ("uvicorn", "uvicorn.access"):
        logging.getLogger(name).addHandler(_LOGGING_HANDLER)
    _capture_installed = True


# ---------------------------------------------------------------- 脱敏

_SECRET_KEYS = (
    "sessdata",
    "bili_jct",
    "buvid3",
    "buvid4",
    "bili_ticket_expires",
    "bili_ticket",
    "dedeuserid__ckmd5",
    "dedeuserid",
    "ac_time_value",
    "music_u",
    "music_a",
    "__csrf",
    "csrf_token",
    "csrf",
    "access_token",
    "refresh_token",
    "id_token",
    "access_key",
    "api_key",
    "apikey",
    "authorization",
    "set-cookie",
    "cookie",
    "token",
    "password",
    "passwd",
    "secret",
)
_KEY = "|".join(re.escape(k) for k in sorted(_SECRET_KEYS, key=len, reverse=True))
_KEY_VALUE_RE = re.compile(
    rf"(?i)(?<![A-Za-z0-9_])({_KEY})([\"']?)(\s*[=:]\s*)"
    r"(\"(?:[^\"\\]|\\.)*\"|'(?:[^'\\]|\\.)*'|[^\s&;,()\[\]{}]+)"
)
_URL_PARAM_RE = re.compile(rf"(?i)([?&](?:{_KEY})=)[^&#\s\"']*")
_COOKIE_HEADER_RE = re.compile(r"(?i)(\b(?:cookie|set-cookie)\s*:\s*)[^\r\n]*")
_AUTH_HEADER_RE = re.compile(
    r"(?i)(\bauthorization\s*:\s*(?:bearer|basic|token)\s+)[^\s,;\"']+"
)
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
_USER_DIR_RE = re.compile(
    r"(?i)((?:[A-Z]:\\Users\\|/Users/|/home/))([^\\/\s:'\"|]+)"
)
_HOME = str(Path.home())
_HOME_RE = re.compile(re.escape(_HOME) + r"(?=[/\\]|$)")


def _redact_key_value(match: re.Match) -> str:
    key, close_quote, sep, value = match.group(1, 2, 3, 4)
    if value[:1] in ('"', "'"):
        return f"{key}{close_quote}{sep}{value[0]}***{value[0]}"
    return f"{key}{close_quote}{sep}***"


def redact(text: str) -> str:
    """对将要外发/落盘的文本做敏感信息脱敏。"""
    if not text:
        return ""
    text = _COOKIE_HEADER_RE.sub(r"\1***", text)
    text = _AUTH_HEADER_RE.sub(r"\1***", text)
    text = _URL_PARAM_RE.sub(r"\1***", text)
    text = _KEY_VALUE_RE.sub(_redact_key_value, text)
    # 用户主目录与常见用户目录(日志/异常里可能出现绝对路径)
    text = _HOME_RE.sub("~", text)
    text = _USER_DIR_RE.sub(r"\1***", text)
    text = _EMAIL_RE.sub("***@***", text)
    return text


# ---------------------------------------------------------------- 截图

def decode_screenshot(data_url: str | None) -> tuple[bytes, str] | None:
    """校验并解码 data URL 截图,返回 (bytes, 扩展名)。"""
    if not data_url:
        return None
    match = _DATA_URL_RE.match(data_url)
    if not match:
        raise ValueError("截图格式不支持(仅支持 PNG/JPEG/WebP)")
    try:
        raw = base64.b64decode(match.group("data"), validate=True)
    except Exception as exc:  # noqa: BLE001 - 统一转成可读错误
        raise ValueError("截图数据损坏") from exc
    if not raw:
        raise ValueError("截图为空")
    if len(raw) > MAX_SCREENSHOT_BYTES:
        raise ValueError("截图过大(上限 15MB)")
    # 校验文件头,避免把任意内容写进 data/feedback
    fmt = match.group("fmt").lower()
    if fmt == "png" and not raw.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("截图数据与格式不符")
    if fmt in ("jpeg", "jpg") and not raw.startswith(b"\xff\xd8\xff"):
        raise ValueError("截图数据与格式不符")
    if fmt == "webp" and not (raw.startswith(b"RIFF") and raw[8:12] == b"WEBP"):
        raise ValueError("截图数据与格式不符")
    return raw, _IMAGE_EXTS[fmt]


# ---------------------------------------------------------------- 环境与报告

def _truncate(text: str, limit: int) -> str:
    text = text or ""
    if len(text) <= limit:
        return text
    return text[:limit] + "…"


def _escape_table(value: str) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def app_version() -> str:
    try:
        from importlib.metadata import version

        return version("bilibili-music-player")
    except Exception:  # noqa: BLE001 - 源码直接运行/打包元数据缺失时兜底
        return "0.1.0"


def _environment_rows(client: dict) -> list[tuple[str, str]]:
    rows = [
        ("应用版本", app_version()),
        ("运行环境", platform.platform()),
        ("Python", f"{platform.python_version()} ({platform.machine()})"),
        ("后端日志", f"{log_count()} 行"),
    ]
    if not client:
        return rows
    if client.get("user_agent"):
        rows.append(("浏览器", _truncate(str(client["user_agent"]), 300)))
    if client.get("language"):
        rows.append(("语言", str(client["language"])))
    viewport, screen = client.get("viewport"), client.get("screen")
    if viewport or screen:
        size = f"窗口 {viewport}" if viewport else ""
        if screen:
            size += f",屏幕 {screen}"
        rows.append(("尺寸", size.strip(" ,")))
    if "logged_in" in client:
        rows.append(("bilibili 登录", "已登录" if client.get("logged_in") else "未登录"))
    if "netease_logged_in" in client:
        rows.append(
            ("网易云登录", "已登录" if client.get("netease_logged_in") else "未登录")
        )
    track = client.get("current_track")
    if isinstance(track, dict) and track.get("title"):
        label = str(track.get("title"))
        if track.get("artist"):
            label += f" — {track.get('artist')}"
        extra = []
        if track.get("quality"):
            extra.append(f"音质 {track['quality']}")
        if track.get("mv"):
            extra.append("MV 模式")
        extra.append("播放中" if track.get("playing") else "已暂停")
        rows.append(("当前曲目", f"{label}({'、'.join(extra)})"))
    return rows


def _normalize_title(title: str, description: str) -> str:
    title = (title or "").strip().splitlines()
    title = title[0].strip() if title else ""
    if not title:
        first = next(
            (line.strip() for line in (description or "").splitlines() if line.strip()),
            "",
        )
        first = re.sub(r"^#{1,6}\s*", "", first)
        title = _truncate(first, 60) if first else "问题反馈"
        title = f"[反馈] {title}"
    title = re.sub(r"\s+", " ", title).strip()
    return _truncate(title, MAX_TITLE)


def _compose_body(
    *,
    description: str,
    env_rows: list[tuple[str, str]],
    log_text: str,
    log_total: int,
    logs_included: bool,
    logs_truncated: bool,
    desc_truncated: bool,
    has_screenshot: bool,
) -> str:
    parts: list[str] = ["### 问题描述", ""]
    parts.append(description.strip() or "(未填写,请在提交前补充问题描述)")
    if desc_truncated:
        parts.append("")
        parts.append(
            "> ⚠️ 内容超过 GitHub 预填长度限制,已截断;可在此处继续补充,完整内容见本地诊断包。"
        )
    parts += ["", "### 环境信息", "", "| 项目 | 值 |", "| --- | --- |"]
    parts += [f"| {label} | {_escape_table(value)} |" for label, value in env_rows]
    if logs_included:
        parts += ["", "### 最近日志(已脱敏)", ""]
        summary = f"展开查看最近 {log_total} 行日志"
        if logs_truncated:
            summary += "(超长,仅保留最近部分)"
        parts += [
            "<details>",
            f"<summary>{summary}</summary>",
            "",
            "```text",
            log_text or "(无日志)",
            "```",
            "",
            "</details>",
        ]
    elif log_total:
        parts += [
            "",
            "> ⚠️ 日志因长度限制未放进预填正文;完整脱敏日志已保存在本地诊断包 `data/feedback/` 下。",
        ]
    if has_screenshot:
        parts += [
            "",
            "### 截图",
            "",
            "> 📷 请在此处粘贴截图(macOS:Cmd+V / Windows/Linux:Ctrl+V);"
            "截图也保存在本地诊断包的 screenshot.png 里,可直接拖入。",
            "> 不需要截图可删除本节。",
        ]
    parts += [
        "",
        "---",
        "",
        "<sub>由 bilibili-music-player 应用内「反馈问题」生成 · 日志已自动脱敏</sub>",
    ]
    return "\n".join(parts) + "\n"


def _issue_url(title: str, body: str) -> str:
    return f"{GITHUB_NEW_ISSUE}?title={quote(title, safe='')}&body={quote(body, safe='')}"


@dataclass
class Report:
    title: str
    body: str  # 预填进 URL 的正文(可能已截断)
    full_body: str  # 完整正文(本地诊断包)
    issue_url: str
    logs: str  # 完整脱敏日志(本地诊断包)
    env_rows: list[tuple[str, str]]
    logs_included: bool
    logs_truncated: bool
    description_truncated: bool
    screenshot: tuple[bytes, str] | None = field(default=None, repr=False)


def _collect_logs(include_logs: bool, log_lines: int, client: dict) -> tuple[str, int]:
    """后端日志 + 前端日志,返回 (脱敏后的完整文本, 总行数)。"""
    if not include_logs:
        return "", 0
    backend = recent_logs(limit=max(10, min(log_lines, 400)))
    frontend: list[str] = []
    for line in (client.get("frontend_logs") or [])[-200:]:
        line = _truncate(str(line).replace("\n", " "), 600).strip()
        if line:
            frontend.append(f"[web] {line}")
    lines = backend + frontend
    return redact("\n".join(lines)), len(lines)


def build_report(
    *,
    description: str = "",
    title: str = "",
    include_logs: bool = True,
    log_lines: int = 200,
    screenshot_data_url: str | None = None,
    client: dict | None = None,
) -> Report:
    """生成 issue 正文/链接与完整诊断文本(不落盘)。"""
    client = client or {}
    description = (description or "").strip()[:MAX_DESCRIPTION]
    title_text = _normalize_title(title, description)
    logs_text, logs_total = _collect_logs(include_logs, log_lines, client)
    env_rows = _environment_rows(client)
    screenshot = decode_screenshot(screenshot_data_url)
    has_screenshot = screenshot is not None

    base_kwargs = dict(
        env_rows=env_rows,
        log_total=logs_total,
        has_screenshot=has_screenshot,
    )
    full_body = _compose_body(
        description=description or "(未填写)",
        log_text=logs_text,
        logs_included=bool(logs_text),
        logs_truncated=False,
        desc_truncated=False,
        **base_kwargs,
    )
    full_url = _issue_url(title_text, full_body)
    if len(full_url) <= MAX_ISSUE_URL:
        return Report(
            title=title_text,
            body=full_body,
            full_body=full_body,
            issue_url=full_url,
            logs=logs_text,
            env_rows=env_rows,
            logs_included=bool(logs_text),
            logs_truncated=False,
            description_truncated=False,
            screenshot=screenshot,
        )

    # 超长:优先裁剪日志(完整日志已保存在本地),再裁剪描述
    log_cap = len(logs_text)
    body, url, truncated_logs = full_body, full_url, False
    while log_cap > 0:
        log_cap = int(log_cap * 0.7)
        if log_cap < 200:
            log_cap = 0
        excerpt = logs_text[-log_cap:] if log_cap else ""
        # 从完整行开始,避免开头出现半行
        head = excerpt.find("\n")
        if 0 <= head < len(excerpt) - 1:
            excerpt = excerpt[head + 1 :]
        body = _compose_body(
            description=description or "(未填写)",
            log_text=excerpt,
            logs_included=bool(excerpt),
            logs_truncated=bool(log_cap),
            desc_truncated=False,
            **base_kwargs,
        )
        url = _issue_url(title_text, body)
        truncated_logs = bool(log_cap)
        if len(url) <= MAX_ISSUE_URL:
            return Report(
                title=title_text,
                body=body,
                full_body=full_body,
                issue_url=url,
                logs=logs_text,
                env_rows=env_rows,
                logs_included=bool(excerpt),
                logs_truncated=truncated_logs,
                description_truncated=False,
                screenshot=screenshot,
            )

    desc = description or "(未填写,请在提交前补充问题描述)"
    desc_cap = len(desc)
    body, url = full_body, full_url
    while desc_cap > 60:
        desc_cap = max(60, int(desc_cap * 0.75))
        excerpt = desc[:desc_cap]
        body = _compose_body(
            description=excerpt,
            log_text="",
            logs_included=False,
            logs_truncated=False,
            desc_truncated=desc_cap < len(desc),
            **base_kwargs,
        )
        url = _issue_url(title_text, body)
        if len(url) <= MAX_ISSUE_URL:
            break
    if len(url) > MAX_ISSUE_URL:
        # 极端兜底(超长标题/环境信息):只保留标题与极短描述,确保链接可用
        short = desc[:60]
        while True:
            body = _compose_body(
                description=short,
                log_text="",
                logs_included=False,
                logs_truncated=False,
                desc_truncated=True,
                **base_kwargs,
            )
            url = _issue_url(title_text, body)
            if len(url) <= MAX_ISSUE_URL or not short:
                break
            short = short[:-1]
    return Report(
        title=title_text,
        body=body,
        full_body=full_body,
        issue_url=url,
        logs=logs_text,
        env_rows=env_rows,
        logs_included=False,
        logs_truncated=False,
        description_truncated=desc_cap < len(desc),
        screenshot=screenshot,
    )


# ---------------------------------------------------------------- 本地诊断包

FEEDBACK_DIR = PROJECT_ROOT / "data" / "feedback"


def save_bundle(report: Report, *, include_logs: bool) -> Path:
    """保存截图/完整日志/报告,返回诊断包目录。"""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    bundle_dir = FEEDBACK_DIR / f"{stamp}-{uuid.uuid4().hex[:6]}"
    bundle_dir.mkdir(parents=True, exist_ok=False)
    (bundle_dir / "report.md").write_text(report.full_body, encoding="utf-8")
    if include_logs:
        (bundle_dir / "logs.txt").write_text(report.logs, encoding="utf-8")
    if report.screenshot:
        raw, ext = report.screenshot
        (bundle_dir / f"screenshot.{ext}").write_bytes(raw)
    context = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "title": report.title,
        "issue_url": report.issue_url,
        "description_truncated": report.description_truncated,
        "logs_truncated": report.logs_truncated,
        "environment": dict(report.env_rows),
    }
    (bundle_dir / "context.json").write_text(
        json.dumps(context, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    _prune_bundles()
    return bundle_dir


def _prune_bundles(keep: int = KEEP_BUNDLES) -> None:
    """只保留最近 keep 个诊断包,避免无限增长。"""

    def mtime(path: Path) -> float:
        try:
            return path.stat().st_mtime
        except OSError:
            return 0.0

    try:
        dirs = sorted(
            (p for p in FEEDBACK_DIR.iterdir() if p.is_dir()),
            key=mtime,
            reverse=True,
        )
    except OSError:
        return
    for old in dirs[keep:]:
        try:
            import shutil

            shutil.rmtree(old)
        except OSError:
            pass


def relative_to_project(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return os.fspath(path)
