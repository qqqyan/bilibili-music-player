"""应用内反馈路由:生成 GitHub issue 预填链接,并保存本地诊断包。

外发内容(issue 正文)与本地诊断包都由 feedback_service 统一脱敏;
截图随请求以 data URL 上传,只写入本机 data/feedback/。
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..services import feedback_service as svc

router = APIRouter(prefix="/api/feedback", tags=["feedback"])


class ClientContext(BaseModel):
    """前端采集的环境信息(可选,字段缺失不影响生成)。"""

    user_agent: str = ""
    language: str = ""
    viewport: str = ""
    screen: str = ""
    device_pixel_ratio: float = 1.0
    logged_in: bool | None = None
    netease_logged_in: bool | None = None
    current_track: dict | None = None
    frontend_logs: list[str] = Field(default_factory=list)


class FeedbackRequest(BaseModel):
    description: str = Field(default="", max_length=svc.MAX_DESCRIPTION)
    title: str = Field(default="", max_length=200)
    include_logs: bool = True
    log_lines: int = Field(default=200, ge=10, le=400)
    screenshot_data_url: str | None = None
    client: ClientContext = Field(default_factory=ClientContext)


def _client_dict(client: ClientContext) -> dict:
    return client.model_dump()


def _build(payload: FeedbackRequest) -> svc.Report:
    try:
        return svc.build_report(
            description=payload.description,
            title=payload.title,
            include_logs=payload.include_logs,
            log_lines=payload.log_lines,
            screenshot_data_url=payload.screenshot_data_url,
            client=_client_dict(payload.client),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _response(report: svc.Report, bundle_path: str | None) -> dict:
    return {
        "repo": svc.GITHUB_REPO,
        "title": report.title,
        "body": report.body,
        "issue_url": report.issue_url,
        "logs_included": report.logs_included,
        "logs_truncated": report.logs_truncated,
        "description_truncated": report.description_truncated,
        "log_lines": len(report.logs.splitlines()) if report.logs else 0,
        "screenshot_saved": bool(report.screenshot) and bundle_path is not None,
        "bundle_path": bundle_path,
    }


@router.get("/info")
async def feedback_info():
    """反馈目标与后端当前可用的日志量。"""
    return {
        "repo": svc.GITHUB_REPO,
        "repo_url": svc.GITHUB_REPO_URL,
        "version": svc.app_version(),
        "log_lines": svc.log_count(),
    }


@router.get("/logs")
async def feedback_logs(limit: int = 200):
    """预览最近日志(已脱敏)。"""
    limit = max(10, min(limit, 400))
    return {"lines": svc.recent_logs(limit), "total": svc.log_count()}


@router.post("/preview")
async def feedback_preview(payload: FeedbackRequest):
    """只生成正文与预填链接,不落盘(检查脱敏结果用)。"""
    return _response(_build(payload), None)


@router.post("/report")
async def feedback_report(payload: FeedbackRequest):
    """生成预填链接,同时保存截图/完整日志/报告到本地诊断包。"""
    report = _build(payload)
    try:
        bundle = svc.save_bundle(
            report, include_logs=payload.include_logs and bool(report.logs)
        )
    except OSError as exc:
        raise HTTPException(status_code=500, detail="保存本地诊断包失败") from exc
    return _response(report, svc.relative_to_project(bundle))
