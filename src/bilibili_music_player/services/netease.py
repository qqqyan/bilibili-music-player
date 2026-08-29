"""网易云音乐客户端(开源渠道:模拟官方 web 端加密协议)。

加密算法移植自社区 NetEaseCloudMusicApi 的 util/crypto.js(原仓库因版权
下架,算法与常量为社区多年稳定版本):
    weapi = 双层 AES-CBC(PKCS7) + 原始 RSA(无填充,encSecKey)

请求层使用 curl_cffi 的 chrome TLS 指纹伪装——网易云风控(易盾)会拒绝
非浏览器指纹的客户端(表现为 8821「安全环境风险」),httpx 直连过不了
扫码登录的最终授权。

用自己账号 cookie 登录后 VIP 曲目可播;匿名可用搜索与免费歌曲 url。
"""

import json
import random
import string

from curl_cffi import requests
from Cryptodome.Cipher import AES

HOST = "https://music.163.com"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# ---------------------------------------------------------------- weapi 常量

_IV = "0102030405060708"
_PRESET_KEY = "0CoJUm6Qyw8W8jud"
_BASE62 = string.ascii_lowercase + string.ascii_uppercase + string.digits

# 社区公开的固定 RSA 公钥(web 端 weapi 验签用)
_RSA_PUBLIC = (
    "MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQDgtQn2JZ34ZC28NWYpAUd98iZ3"
    "7BUrX/aKzmFbt7clFSs6sXqHauqKWqdtLkF2KexO40H1YTX8z2lSgBBOAxLsvakl"
    "V8k4cBFK9snQXE9/DDaFt6Rr7iVZMldczhC0JNgTz+SHXT6CBHuX3e9SdB1Ua44o"
    "ncaTWz7OBGLbCiK45wIDAQAB"
)

# 音质档:(标签, quality_id=请求码率 br, br 参数)
# 无损(999000)需登录/VIP,返回 flac;其余返回 mp3
NETEASE_LEVELS = [
    ("无损", 999000, 999000),
    ("极高", 320000, 320000),
    ("较高", 192000, 192000),
    ("标准", 128000, 128000),
]
NETEASE_MIME = {"mp3": "audio/mpeg", "flac": "audio/flac"}


# ---------------------------------------------------------------- 加密

def _aes_cbc_b64(text: str, key: str, iv: str) -> str:
    """AES-CBC PKCS7 加密,输出 base64(等价 CryptoJS AES.encrypt 默认)。"""
    import base64

    cipher = AES.new(key.encode("utf-8"), AES.MODE_CBC, iv.encode("utf-8"))
    pad = 16 - len(text.encode("utf-8")) % 16
    data = text.encode("utf-8") + bytes([pad]) * pad
    return base64.b64encode(cipher.encrypt(data)).decode("ascii")


def _rsa_raw_hex(msg: str) -> str:
    """原始 RSA 加密(无填充):pow(msg_bytes, e, n) → hex 左补零 256 位。

    公钥为 1024 位 RSA;msg 为反转后的 16 字节密钥(128 位,恒小于 n)。
    Cryptodome 不提供原始 RSA,用 import_key 取 n/e 后整数幂实现。
    """
    from Cryptodome.PublicKey import RSA

    key = RSA.import_key(f"-----BEGIN PUBLIC KEY-----\n{_RSA_PUBLIC}\n-----END PUBLIC KEY-----")
    m = int.from_bytes(msg.encode("utf-8"), "big")
    return format(pow(m, key.e, key.n), "x").zfill(256)


def weapi(payload: dict) -> dict:
    """把 JSON payload 加密为 weapi 表单体。"""
    text = json.dumps(payload, separators=(",", ":"))
    secret = "".join(random.choices(_BASE62, k=16))
    params = _aes_cbc_b64(_aes_cbc_b64(text, _PRESET_KEY, _IV), secret, _IV)
    return {"params": params, "encSecKey": _rsa_raw_hex(secret[::-1])}


# ---------------------------------------------------------------- 请求层

_BASE_HEADERS = {"User-Agent": UA, "Referer": f"{HOST}/"}


def _post(path: str, payload: dict, cookie: str = "") -> dict:
    """POST weapi 接口(chrome TLS 指纹),返回 JSON(非 0 code 抛 ValueError)。"""
    headers = {**_BASE_HEADERS, "Content-Type": "application/x-www-form-urlencoded"}
    if cookie:
        headers["Cookie"] = cookie
    resp = requests.post(
        f"{HOST}{path}",
        data=weapi(payload),
        headers=headers,
        timeout=15,
        impersonate="chrome",
    )
    try:
        data = resp.json()
    except json.JSONDecodeError as e:
        raise ValueError(f"网易云响应异常: HTTP {resp.status_code}") from e
    if data.get("code") not in (200, 0, None):
        raise ValueError(f"网易云接口错误 {data.get('code')}: {data.get('message', '')[:80]}")
    return data


def _get(path: str, cookie: str = "", params: dict | None = None) -> dict:
    headers = {**_BASE_HEADERS}
    if cookie:
        headers["Cookie"] = cookie
    resp = requests.get(
        f"{HOST}{path}",
        params=params or {},
        headers=headers,
        timeout=15,
        impersonate="chrome",
    )
    return resp.json()


# ---------------------------------------------------------------- 登录
# 2026 现行 web 扫码流程(实测验证):
#   POST /weapi/login/qrcode/unikey {type:1} → unikey
#   POST /weapi/login/qrcode/client/login {key, type:1} → 801/802/803
# 关键点:
#   1) 轮询必须携带同一会话 cookie(服务端只向建立二维码的会话发放 MUSIC_U)
#   2) 请求必须带浏览器 TLS 指纹(否则 802 确认后被 8821 安全风控拒绝)

class QrSession:
    """一次扫码登录的会话:curl_cffi 会话(chrome 指纹 + cookie jar)。

    完整模拟官方登录页流程,风控(8821 安全环境风险)检查的不止 TLS 指纹:
      1) 预置真实浏览器环境的设备指纹 cookie(data/netease_env.json,
         来自用户浏览器抓包;风控按设备画像放行)
      2) 预热登录页(拿 JSESSIONID-WYYY 等会话 cookie)
      3) 走官方 /api/web/qrcode/get 步骤(服务端会话状态标记)
      4) weapi unikey + 轮询,请求带 Origin(浏览器同源 POST 行为)
    """

    def __init__(self) -> None:
        self.client = requests.Session(impersonate="chrome")
        self.client.headers.update({**_BASE_HEADERS, "Origin": HOST})
        # 预置环境 cookie 种子(设备指纹画像)
        try:
            from ..config import PROJECT_ROOT

            env_file = PROJECT_ROOT / "data" / "netease_env.json"
            if env_file.exists():
                for k, v in json.loads(env_file.read_text(encoding="utf-8")).items():
                    self.client.cookies.set(k, v)
        except Exception:
            pass
        for url in (f"{HOST}/", f"{HOST}/login"):
            try:
                self.client.get(url, timeout=15)
            except requests.RequestsError:
                pass
        # 官方现行流程的二维码获取步骤(图片不用,但要踩这个会话标记)
        try:
            self.client.post(
                f"{HOST}/api/web/qrcode/get",
                data={"url": f"{HOST}/login", "size": "180"},
                timeout=15,
            )
        except requests.RequestsError:
            pass
        self.unikey = ""

    def create_qr(self) -> str:
        """获取 unikey(会话内)。"""
        r = self.client.post(
            f"{HOST}/weapi/login/qrcode/unikey",
            data=weapi({"type": 1}),
            timeout=15,
        )
        data = r.json()
        key = data.get("unikey")
        if not key:
            raise ValueError(f"获取登录二维码失败: {data.get('message', '')[:60]}")
        self.unikey = key
        return key

    def poll(self) -> tuple[str, dict, str]:
        """轮询扫码状态(会话内)→ (状态, 数据, 登录 cookie)。"""
        r = self.client.post(
            f"{HOST}/weapi/login/qrcode/client/login",
            data=weapi({"key": self.unikey, "type": 1}),
            timeout=15,
        )
        data = r.json()
        code = data.get("code")
        if code == 803:
            # 会话 jar 已累积 Set-Cookie(MUSIC_U/__csrf 等),整串作为登录态
            jar = self.client.cookies.get_dict()
            cookie = "; ".join(f"{k}={v}" for k, v in jar.items())
            return "done", data, cookie
        if code == 800:
            return "expired", data, ""
        if code == 802:
            return "confirm", data, ""
        if code == 801:
            return "scan", data, ""
        print(f"[netease-qr] 未知响应 code={code}: {str(data)[:200]}", flush=True)
        return "wait", data, ""

    def close(self) -> None:
        try:
            self.client.close()
        except Exception:
            pass


def qr_key() -> str:
    """获取扫码登录 unikey(无会话——保留给测试用)。"""
    data = _post("/weapi/login/qrcode/unikey", {"type": 1})
    key = data.get("unikey")
    if not key:
        raise ValueError("获取登录二维码失败")
    return key


def qr_svg(unikey: str) -> str:
    """把 unikey 画成本地二维码(SVG 文本),内容为官方登录确认链接。"""
    import qrcode
    import qrcode.image.svg

    qr = qrcode.QRCode(border=1)
    qr.add_data(f"https://music.163.com/login?codekey={unikey}")
    qr.make(fit=True)
    img = qr.make_image(image_factory=qrcode.image.svg.SvgPathImage)
    return img.to_string().decode("utf-8")


def qr_check(unikey: str) -> tuple[str, dict, dict]:
    """无会话轮询(保留给测试用)。"""
    r = requests.post(
        f"{HOST}/weapi/login/qrcode/client/login",
        data=weapi({"key": unikey, "type": 1}),
        headers={**_BASE_HEADERS, "Content-Type": "application/x-www-form-urlencoded"},
        timeout=15,
        impersonate="chrome",
    )
    data = r.json()
    code = data.get("code")
    if code == 803:
        return "done", data, {}
    if code == 800:
        return "expired", data, {}
    if code == 802:
        return "confirm", data, {}
    if code == 801:
        return "scan", data, {}
    return "wait", data, {}


def user_detail(cookie: str) -> dict:
    """当前登录用户信息(昵称/头像)。"""
    csrf = ""
    for part in cookie.split(";"):
        k, _, v = part.strip().partition("=")
        if k == "__csrf":
            csrf = v
    data = _post(f"/weapi/w/nuser/account/get?csrf_token={csrf}", {}, cookie)
    profile = data.get("profile") or {}
    return {
        "name": profile.get("nickname") or "",
        "face": profile.get("avatarUrl") or "",
    }


def cookie_user(cookie: str) -> dict | None:
    """校验 cookie 有效性并返回用户信息;无效返回 None。"""
    if "MUSIC_U=" not in cookie:
        return None
    try:
        user = user_detail(cookie)
        return user if user.get("name") else None
    except Exception:
        return None


# 环境类 cookie 键(设备指纹画像,登录成功后自保鲜写入种子文件)
_ENV_KEYS = {
    "NMTID", "WEVNSM", "WNMCID", "WM_NI", "WM_NIKE", "WM_TID", "__snaker__id",
    "ntes_utid", "sDeviceId", "ntes_kaola_ad", "JSESSIONID-WYYY",
    "_iuqxldmzr_", "NTES_P_UTID", "_ntes_nnid", "_ntes_nuid",
    "MUSIC_A_T", "MUSIC_R_T", "gdxidpyhxdE",
}


def save_env_seed(cookie: str) -> None:
    """登录成功后把环境类 cookie 写回种子文件(data/netease_env.json)。

    种子随时间自我更新,本机后续扫码免手工维护。
    """
    try:
        from ..config import PROJECT_ROOT

        env_file = PROJECT_ROOT / "data" / "netease_env.json"
        seed: dict = {}
        if env_file.exists():
            try:
                seed = json.loads(env_file.read_text(encoding="utf-8"))
            except Exception:
                seed = {}
        for part in cookie.split(";"):
            if "=" in part:
                k, v = part.strip().split("=", 1)
                if k in _ENV_KEYS:
                    seed[k] = v
        env_file.write_text(
            json.dumps(seed, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception:
        pass


def refresh_cookie(cookie: str) -> str:
    """刷新登录 cookie(/login/refresh weapi,响应 Set-Cookie 带新 MUSIC_U)。"""
    headers = {**_BASE_HEADERS, "Content-Type": "application/x-www-form-urlencoded"}
    resp = requests.post(
        f"{HOST}/login/refresh",
        data=weapi({"csrf_token": ""}),
        headers={**headers, "Cookie": cookie},
        timeout=15,
        impersonate="chrome",
    )
    merged = cookie
    jar = resp.cookies.get_dict() if hasattr(resp, "cookies") else {}
    for name in ("MUSIC_U", "__csrf"):
        if name in jar:
            merged = _replace_cookie(merged, name, jar[name])
    return merged


def _replace_cookie(cookie: str, key: str, value: str) -> str:
    parts = cookie.split(";")
    out = []
    for p in parts:
        k, _, _ = p.strip().partition("=")
        if k == key:
            continue
        out.append(p)
    out.append(f"{key}={value}")
    return ";".join(out)


# ---------------------------------------------------------------- 数据
# 搜索/歌曲 URL/详情走老式明文接口(weapi cloudsearch 匿名已被墙,老接口实测可用)

def search(keyword: str, page: int = 1, cookie: str = "") -> tuple[list[dict], int]:
    """搜索歌曲 → (条目列表, 总命中数)。"""
    data = _get(
        "/api/search/get/web",
        cookie,
        {"s": keyword, "type": 1, "limit": 20, "offset": (page - 1) * 20},
    )
    result = data.get("result") or {}
    total = result.get("songCount") or 0
    return result.get("songs") or [], int(total)


def song_url(song_id: int, br: int, cookie: str = "") -> tuple[str, str]:
    """获取播放地址 → (url, 编码格式 mp3/flac);无地址返回 ("", "")。"""
    headers = {**_BASE_HEADERS}
    if cookie:
        headers["Cookie"] = cookie
    resp = requests.post(
        f"{HOST}/api/song/enhance/player/url",
        data={"ids": f"[{song_id}]", "br": br},
        headers=headers,
        timeout=15,
        impersonate="chrome",
    )
    data = resp.json()
    items = data.get("data") or []
    if not items:
        return "", ""
    it = items[0]
    if not it.get("url"):
        return "", ""
    # type 字段:"flac"=无损,"mp3"=有损(旧接口无 type 时按请求档推断)
    kind = it.get("type") or ("flac" if br >= 999000 else "mp3")
    return it["url"], kind


def song_detail(song_ids: list[int], cookie: str = "") -> list[dict]:
    """歌曲元数据(名称/歌手/专辑/封面/时长)。"""
    data = _get("/api/song/detail", cookie, {"ids": json.dumps(song_ids)})
    return data.get("songs") or []
