"""应用内反馈:脱敏、issue 预填、截图校验与本地诊断包。"""

import base64
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from bilibili_music_player.services import feedback_service as svc

# 1x1 透明 PNG
PNG_1PX = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"
    "YPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)
PNG_DATA_URL = f"data:image/png;base64,{PNG_1PX}"


@pytest.fixture(autouse=True)
def _clean_logs():
    svc.clear_logs()
    yield
    svc.clear_logs()


# ---------------------------------------------------------------- 脱敏


def test_redact_credentials_cookies_and_paths():
    text = (
        "SESSDATA=abc123%2Cdef; bili_jct=deadbeef\n"
        "cookie: SESSDATA=xyz; MUSIC_U=mmm\n"
        "Authorization: Bearer eyJhbGciOiJ.payload.sig\n"
        "https://api.bilibili.com/x?access_key=url-secret&w_rid=ok\n"
        '{"sessdata": "json-secret", "normal": "keep"}\n'
        "/Users/alice/project/data/auth.json C:\\Users\\bob\\app\\data\n"
        "contact me at alice@example.com\n"
        "[player] audio ended → next\n"
    )
    out = svc.redact(text)

    for secret in (
        "abc123%2Cdef",
        "deadbeef",
        "xyz",
        "mmm",
        "eyJhbGciOiJ",
        "url-secret",
        "json-secret",
        "alice",
        "bob",
        "alice@example.com",
    ):
        assert secret not in out
    # 非敏感内容与普通播放日志保留,便于排查
    assert "w_rid=ok" in out
    assert "audio ended → next" in out
    assert "keep" in out


def test_redact_keeps_plain_log_lines():
    line = "[download] 完成:bv1xx411c7mD"
    assert svc.redact(line) == line


# ---------------------------------------------------------------- 报告生成


def _client(**overrides):
    client = {
        "user_agent": "Mozilla/5.0 (Macintosh) Chrome/140.0",
        "language": "zh-CN",
        "viewport": "1440x900",
        "screen": "2560x1440",
        "device_pixel_ratio": 2,
        "logged_in": True,
        "netease_logged_in": False,
        "current_track": {
            "id": "bvTEST",
            "title": "测试歌曲",
            "artist": "测试 UP",
            "playing": True,
            "quality": "192K",
            "mv": True,
        },
        "frontend_logs": ["[web] token=frontsecret 播放失败"],
    }
    client.update(overrides)
    return client


def test_build_report_structure_and_redaction():
    svc.record_log("SESSDATA=supersecret 普通日志")
    report = svc.build_report(
        description="MV 播放时下一首失效",
        include_logs=True,
        log_lines=50,
        client=_client(),
    )

    assert report.title.startswith("[反馈] ")
    assert "MV 播放时下一首失效" in report.body
    assert "### 环境信息" in report.body
    assert "### 最近日志(已脱敏)" in report.body
    assert "测试歌曲" in report.body
    assert "supersecret" not in report.body
    assert "supersecret" not in report.issue_url
    assert "frontsecret" not in report.body
    assert "已自动脱敏" in report.body
    assert report.issue_url.startswith(
        "https://github.com/qqqyan/bilibili-music-player/issues/new?title="
    )
    assert "%E5%8F%8D%E9%A6%88" in report.issue_url  # 「反馈」


def test_build_report_without_logs_omits_log_section():
    report = svc.build_report(
        description="搜索无结果",
        include_logs=False,
        client=_client(),
    )
    assert not report.logs_included
    assert "### 最近日志" not in report.body
    assert report.logs == ""


def test_build_report_escapes_table_and_truncates_long_input():
    svc.record_log("x" * 5000)
    report = svc.build_report(
        description="问题 " + "很长" * 4000,
        include_logs=True,
        log_lines=400,
        client=_client(user_agent="UA|with|pipes"),
    )
    assert len(report.issue_url) <= svc.MAX_ISSUE_URL
    assert report.logs_truncated or report.description_truncated
    # 完整正文留给本地诊断包,应包含未截断日志
    assert len(report.full_body) >= len(report.body)
    assert "UA\\|with\\|pipes" in report.body


def test_build_report_always_fits_when_description_is_huge():
    report = svc.build_report(
        description="播放异常" * 6000,
        include_logs=False,
        client=_client(),
    )
    assert len(report.issue_url) <= svc.MAX_ISSUE_URL
    assert report.description_truncated
    assert "已截断" in report.body


# ---------------------------------------------------------------- 截图


def test_decode_screenshot_accepts_valid_png():
    raw, ext = svc.decode_screenshot(PNG_DATA_URL)
    assert raw.startswith(b"\x89PNG")
    assert ext == "png"


@pytest.mark.parametrize(
    "data_url",
    [
        "not-a-data-url",
        "data:image/gif;base64,R0lGODlhAQABAAAAACw=",
        "data:image/png;base64,aGVsbG8=",  # 文件头不是 PNG
        "data:image/png;base64,%%%",
    ],
)
def test_decode_screenshot_rejects_invalid(data_url):
    with pytest.raises(ValueError):
        svc.decode_screenshot(data_url)


def test_decode_screenshot_rejects_oversize(monkeypatch):
    monkeypatch.setattr(svc, "MAX_SCREENSHOT_BYTES", 8)
    with pytest.raises(ValueError, match="截图过大"):
        svc.decode_screenshot(PNG_DATA_URL)


# ---------------------------------------------------------------- API


def test_feedback_info_and_logs(test_app):
    svc.record_log("SESSDATA=api-secret 请求失败")
    with TestClient(test_app) as client:
        info = client.get("/api/feedback/info")
        logs = client.get("/api/feedback/logs?limit=10")
    assert info.status_code == 200
    assert info.json()["repo"] == "qqqyan/bilibili-music-player"
    assert info.json()["log_lines"] == 1
    assert logs.status_code == 200
    body = logs.json()
    assert body["total"] == 1
    assert "api-secret" not in "\n".join(body["lines"])


def test_feedback_preview_does_not_save(test_app, tmp_path, monkeypatch):
    monkeypatch.setattr(svc, "FEEDBACK_DIR", tmp_path / "feedback")
    with TestClient(test_app) as client:
        resp = client.post(
            "/api/feedback/preview",
            json={"description": "预览问题", "include_logs": True, "client": _client()},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["issue_url"].startswith("https://github.com/")
    assert data["bundle_path"] is None
    assert not (tmp_path / "feedback").exists()


def test_feedback_report_saves_bundle(test_app, tmp_path, monkeypatch):
    bundle_root = tmp_path / "feedback"
    monkeypatch.setattr(svc, "FEEDBACK_DIR", bundle_root)
    svc.record_log("SESSDATA=bundle-secret 下载失败")

    payload = {
        "description": "下载完成后播放列表缓存图标不刷新",
        "title": "缓存图标不刷新",
        "include_logs": True,
        "log_lines": 100,
        "screenshot_data_url": PNG_DATA_URL,
        "client": _client(),
    }
    with TestClient(test_app) as client:
        resp = client.post("/api/feedback/report", json=payload)

    assert resp.status_code == 200
    data = resp.json()
    assert data["title"] == "缓存图标不刷新"
    assert data["screenshot_saved"] is True
    assert data["logs_included"] is True
    assert "bundle-secret" not in data["body"]
    assert "bundle-secret" not in data["issue_url"]

    bundle = tmp_path / "feedback" / Path(data["bundle_path"]).name
    assert bundle.is_dir()
    assert (bundle / "screenshot.png").read_bytes() == base64.b64decode(PNG_1PX)
    logs = (bundle / "logs.txt").read_text(encoding="utf-8")
    assert "bundle-secret" not in logs
    report = (bundle / "report.md").read_text(encoding="utf-8")
    assert "下载完成后播放列表缓存图标不刷新" in report
    context = (bundle / "context.json").read_text(encoding="utf-8")
    assert "缓存图标不刷新" in context


def test_feedback_report_rejects_bad_screenshot(test_app):
    with TestClient(test_app) as client:
        resp = client.post(
            "/api/feedback/report",
            json={"description": "x", "screenshot_data_url": "data:image/png;base64,aGVsbG8="},
        )
    assert resp.status_code == 400
