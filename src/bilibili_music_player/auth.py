"""登录 API:bilibili 二维码登录 + 手动凭证填写。

二维码流程:POST /qrcode 生成(返回 PNG) → 前端轮询 status → DONE 时
后端保存凭证(含 ac_time_value 便于续期)并热更新全局 Credential。
"""

import base64
import json
import time
import uuid

from bilibili_api import login_v2, user
from bilibili_api.exceptions import LoginError
from bilibili_api.utils.geetest import Geetest, GeetestType
from bilibili_api.utils.network import Api, Credential, get_client
from bilibili_api.utils.utils import get_api
from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

LOGIN_API = get_api("login")

from . import auth_store
from .config import get_credential, is_logged_in, refresh_credential

router = APIRouter(prefix="/api/auth")

# 二维码会话:session_id -> {login, created_at}
_qr_sessions: dict[str, dict] = {}
_QR_TTL = 180  # 二维码有效期(秒)

# 密码登录的极验验证会话:session_id -> {geetest, created_at}
_geetest_sessions: dict[str, dict] = {}
_GEETEST_TTL = 300  # 验证会话有效期(秒)


def _purge_expired() -> None:
    now = time.time()
    for sid in [s for s, v in _qr_sessions.items() if now - v["created_at"] > _QR_TTL]:
        _qr_sessions.pop(sid, None)


async def try_refresh_credential() -> bool:
    """检查当前凭证有效性,无效时用 refresh_token(ac_time_value)续期。

    由服务启动时与 /api/auth/status 调用;成功保存新凭证并热更新。
    """
    cred = get_credential()
    if not cred.sessdata:
        return False
    try:
        if await cred.check_valid():
            return True
        await cred.refresh()  # zoku 用 ac_time_value 换取新 SESSDATA 等
        record = auth_store.load_auth() or {}
        fields = {
            "sessdata": cred.sessdata,
            "bili_jct": cred.bili_jct,
            "dedeuserid": cred.dedeuserid,
            "ac_time_value": getattr(cred, "ac_time_value", ""),
            "buvid3": getattr(cred, "buvid3", ""),
            "buvid4": getattr(cred, "buvid4", ""),
        }
        auth_store.save_auth(
            {**(record.get("credentials") or {}), **fields}, record.get("user")
        )
        refresh_credential()
        print("[auth] 凭证已自动刷新续期", flush=True)
        return True
    except Exception as e:
        print(f"[auth] 凭证刷新失败(可重新登录): {str(e)[:120]}", flush=True)
        return False


async def _save_login(cred: Credential) -> dict:
    """保存凭证、拉取用户信息、热更新全局凭证。返回用户信息。"""
    fields = {
        "sessdata": cred.sessdata,
        "bili_jct": cred.bili_jct,
        "dedeuserid": cred.dedeuserid,
        "ac_time_value": getattr(cred, "ac_time_value", ""),
        "buvid3": getattr(cred, "buvid3", ""),
        "buvid4": getattr(cred, "buvid4", ""),
    }
    user_info: dict | None = None
    try:
        info = (await user.get_self_info(cred)) or {}
        user_info = {"name": info.get("name", ""), "face": info.get("face", "")}
    except Exception as e:
        print(f"[auth] 获取用户信息失败(不影响登录): {e}", flush=True)
    auth_store.save_auth(fields, user_info)
    refresh_credential()
    return user_info or {}


@router.post("/qrcode")
async def create_qrcode():
    """生成登录二维码,返回 session_id 与 PNG data URL。"""
    qr = login_v2.QrCodeLogin(platform=login_v2.QrCodeLoginChannel.WEB)
    await qr.generate_qrcode()
    picture = qr.get_qrcode_picture()
    img_b64 = base64.b64encode(picture.content).decode()
    session_id = uuid.uuid4().hex
    _qr_sessions[session_id] = {"login": qr, "created_at": time.time()}
    _purge_expired()
    return {
        "session_id": session_id,
        "image_data_url": f"data:image/png;base64,{img_b64}",
        "expires_in": _QR_TTL,
    }


@router.get("/qrcode/status/{session_id}")
async def qrcode_status(session_id: str):
    """轮询二维码登录状态:scan / confirm / timeout / done / error。

    不依赖 zoku 的 check_state(其字符串解析凭证不可靠,且会消费确认事件),
    自己请求 poll 接口,凭证取自确认成功时响应的 Set-Cookie。
    """
    sess = _qr_sessions.get(session_id)
    if sess is None:
        return {"status": "timeout"}
    if time.time() - sess["created_at"] > _QR_TTL:
        _qr_sessions.pop(session_id, None)
        return {"status": "timeout"}
    qr: login_v2.QrCodeLogin = sess["login"]
    qr_key = qr._QrCodeLogin__qr_key
    poll_api = LOGIN_API["qrcode"]["web"]["get_events"]
    client = get_client()
    resp = await client.request(
        method=poll_api.get("method", "GET"),
        url=poll_api["url"],
        params={"qrcode_key": qr_key},
    )
    events = resp.json()
    # 响应为两层结构:外层 code 是请求级状态,内层 data.code 才是二维码状态
    data = events.get("data") or {}
    code = data.get("code")
    print(
        f"[auth] poll: qr_code={code} msg={str(data.get('message'))[:40]} "
        f"cookies={list(resp.cookies.keys())}",
        flush=True,
    )
    if code == 86101:
        return {"status": "scan"}
    if code == 86090:
        return {"status": "confirm"}
    if code == 86038:
        _qr_sessions.pop(session_id, None)
        return {"status": "timeout"}
    if code != 0:
        return {
            "status": "error",
            "message": data.get("message") or f"登录接口返回 code={code}",
        }
    # 内层 code == 0:确认成功。凭证优先取响应 Set-Cookie,
    # 否则解析 data.url(crossDomain 链接,可能为空或参数形式)
    cookies = resp.cookies
    cred = Credential(
        sessdata=str(cookies.get("SESSDATA", "")),
        bili_jct=str(cookies.get("bili_jct", "")),
        dedeuserid=str(cookies.get("DedeUserID", "")),
        ac_time_value=data.get("refresh_token", ""),
    )
    if not cred.sessdata:
        # 兜底:从 data.url 的 query 参数解析
        cred_url = data.get("url") or ""
        if "?" in cred_url:
            params = dict(
                pair.split("=", 1)
                for pair in cred_url.split("?")[1].split("&")
                if "=" in pair
            )
            cred = Credential(
                sessdata=params.get("SESSDATA", ""),
                bili_jct=params.get("bili_jct", ""),
                dedeuserid=params.get("DedeUserID", ""),
                ac_time_value=data.get("refresh_token", ""),
            )
    if not cred.sessdata:
        _qr_sessions.pop(session_id, None)
        raise HTTPException(
            status_code=502,
            detail=f"登录确认成功但凭证解析失败,请重试(cookies keys={list(cookies.keys())})",
        )
    user_info = await _save_login(cred)
    _qr_sessions.pop(session_id, None)
    return {"status": "done", "user": user_info}


@router.get("/status")
async def auth_status():
    """当前登录状态与用户信息(顺带检查/续期凭证)。"""
    if is_logged_in():
        await try_refresh_credential()
    record = auth_store.load_auth()
    return {
        "logged_in": is_logged_in(),
        "user": (record or {}).get("user") or None,
        "env_login": not record and is_logged_in(),  # 通过 .env 配置的登录
    }


@router.post("/logout")
async def logout():
    """清除登录凭证。"""
    auth_store.clear_auth()
    refresh_credential()
    return {"ok": True}


class CredentialForm(BaseModel):
    sessdata: str = ""
    bili_jct: str = ""
    dedeuserid: str = ""
    buvid3: str = ""
    buvid4: str = ""


@router.post("/password/prepare")
async def password_prepare():
    """密码登录第一步:创建极验验证,返回内嵌验证页 URL(本服务托管)。

    不再使用 zoku 的本地模板(其 popup 弹窗在 iframe 中会裁切且依赖 jquery CDN),
    验证页由本服务渲染(embed 内嵌模式),结果由页面内 fetch 回传。
    """
    geetest = Geetest()
    await geetest.generate_test(GeetestType.LOGIN)
    session_id = uuid.uuid4().hex
    _geetest_sessions[session_id] = {"geetest": geetest, "created_at": time.time()}
    # 清理过期会话
    now = time.time()
    for sid in [
        s for s, v in _geetest_sessions.items() if now - v["created_at"] > _GEETEST_TTL
    ]:
        _geetest_sessions.pop(sid, None)
    return {
        "session_id": session_id,
        "geetest_url": f"/api/auth/geetest-page/{session_id}",
    }


# 内嵌式极验验证页:无 jquery 依赖,embed 模式完整展示验证 UI,
# 验证成功自动回传结果
GEETEST_PAGE_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>人机验证</title>
<style>
  body { margin: 0; padding: 12px 8px; text-align: center; font-family: "PingFang SC", "Microsoft YaHei", sans-serif; background: #fff; }
  .tip { font-size: 13px; color: #555; margin-bottom: 10px; }
  #captcha { width: 100%; min-height: 240px; }
  #wait { color: #999; font-size: 13px; padding: 60px 0; }
  #ok { display: none; color: #2e7d32; font-size: 13px; margin-top: 8px; }
</style>
</head>
<body>
  <div class="tip">请完成下方人机验证</div>
  <div id="captcha"><div id="wait">验证码加载中…</div></div>
  <div id="ok">✓ 验证完成,正在登录…</div>
  <script src="https://static.geetest.com/static/tools/gt.js"></script>
  <script>
    function postResult(result) {
      document.getElementById("ok").style.display = "block";
      fetch("/api/auth/geetest-result/__SESSION_ID__", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          validate: result.geetest_validate,
          seccode: result.geetest_seccode,
        }),
      }).catch(function () { /* 结果回传失败时父页面轮询会发现未完成 */ });
    }
    function boot() {
      if (!window.initGeetest) {
        document.getElementById("wait").textContent = "极验 SDK 加载失败,请刷新重试";
        return;
      }
      initGeetest({
        gt: "__GT__",
        challenge: "__CHALLENGE__",
        offline: false,
        new_captcha: true,
        product: "embed", // 内嵌完整展示,避免 popup 弹层被 iframe 裁切
        width: "100%",
        https: true,
        lang: "zh-cn",
      }, function (captchaObj) {
        captchaObj.appendTo("#captcha");
        captchaObj.onReady(function () {
          var w = document.getElementById("wait");
          if (w) w.style.display = "none";
        });
        captchaObj.onSuccess(function () {
          postResult(captchaObj.getValidate());
        });
        captchaObj.onError(function () {
          document.getElementById("wait").textContent = "验证加载出错,请刷新重试";
        });
      });
    }
    boot();
  </script>
</body>
</html>"""


class GeetestResultForm(BaseModel):
    validate: str
    seccode: str


@router.get("/geetest-page/{session_id}")
async def geetest_page(session_id: str):
    """验证页(embed 模式,注入 gt/challenge)。"""
    sess = _geetest_sessions.get(session_id)
    if sess is None:
        return HTMLResponse("<p style='padding:40px;text-align:center'>验证会话不存在或已过期,请重新发起登录</p>")
    info = sess["geetest"].get_info()
    html = (
        GEETEST_PAGE_HTML.replace("__GT__", info.gt)
        .replace("__CHALLENGE__", info.challenge)
        .replace("__SESSION_ID__", session_id)
    )
    return HTMLResponse(html)


@router.post("/geetest-result/{session_id}")
async def geetest_result(session_id: str, form: GeetestResultForm):
    """验证页回传人机验证结果。"""
    sess = _geetest_sessions.get(session_id)
    if sess is None:
        raise HTTPException(status_code=400, detail="验证会话已过期")
    geetest: Geetest = sess["geetest"]
    geetest.validate = form.validate
    geetest.seccode = form.seccode
    geetest.done = True
    return {"ok": True}


@router.get("/password/geetest-status/{session_id}")
async def password_geetest_status(session_id: str):
    """轮询人机验证是否完成。"""
    sess = _geetest_sessions.get(session_id)
    if sess is None:
        return {"done": False, "expired": True}
    if time.time() - sess["created_at"] > _GEETEST_TTL:
        _geetest_sessions.pop(session_id, None)
        return {"done": False, "expired": True}
    return {"done": sess["geetest"].has_done(), "expired": False}


class PasswordForm(BaseModel):
    session_id: str
    username: str
    password: str


@router.post("/password")
async def password_login(form: PasswordForm):
    """密码登录第二步:人机验证完成后提交账号密码。"""
    sess = _geetest_sessions.get(form.session_id)
    if sess is None or time.time() - sess["created_at"] > _GEETEST_TTL:
        raise HTTPException(status_code=400, detail="验证会话已过期,请重新发起登录")
    geetest: Geetest = sess["geetest"]
    if not geetest.has_done():
        raise HTTPException(status_code=400, detail="人机验证尚未完成")
    try:
        result = await login_v2.login_with_password(form.username, form.password, geetest)
    except LoginError as e:
        raise HTTPException(status_code=400, detail=f"登录失败: {str(e)[:120]}")
    finally:
        _geetest_sessions.pop(form.session_id, None)
    if isinstance(result, login_v2.LoginCheck):
        # 触发二次验证(短信/设备验证等),扫码登录不受此限制
        raise HTTPException(
            status_code=400, detail="账号需要二次验证(短信等),请改用扫码登录"
        )
    user_info = await _save_login(result)
    return {"ok": True, "user": user_info}


@router.post("/credential")
async def submit_credential(form: CredentialForm):
    """手动填写凭证登录(从浏览器 Cookie 复制),提交前验证有效性。"""
    if not form.sessdata:
        raise HTTPException(status_code=400, detail="SESSDATA 不能为空")
    fields = form.model_dump()
    cred = Credential(**fields)
    try:
        info = (await user.get_self_info(cred)) or {}
        user_info = {"name": info.get("name", ""), "face": info.get("face", "")}
    except Exception as e:
        raise HTTPException(
            status_code=400, detail=f"凭证无效或已过期: {str(e)[:120]}"
        )
    auth_store.save_auth(fields, user_info)
    refresh_credential()
    return {"ok": True, "user": user_info}
