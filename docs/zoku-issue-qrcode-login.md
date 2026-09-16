# 给 bilibili-api-zoku 提 issue:二维码登录 check_state 不可靠(实测文档)

> 整理时间:2026-08-28。用于向 [bromothymolb/bilibili-api-zoku](https://github.com/bromothymolb/bilibili-api-zoku) 提交 issue/PR 时引用。
> 依据:bilibili-music-player 项目登录功能实测(2026-08,服务端长期运行验证)。

## 问题摘要

`QrCodeLogin.check_state()` 的主干(请求 `get_events`、判内层 `code`)没有问题——`Api.result` 已提取响应 data,`events["code"]` 即内层状态码。**问题只在最后一步**:它假设凭证在 `data.url` 的 query 参数里并做 `split("?")[1].split("&")` 解析,但凭证实际在响应的 **Set-Cookie** 里(SESSDATA / bili_jct / DedeUserID)。实测两种失败模式:

| 场景 | `data.url` 实测值 | `check_state` 表现 |
| --- | --- | --- |
| 2026-08-26 项目实测 | 空 | `split("?")[1]` 抛 `IndexError` |
| 2026-08-28 独立脚本实测 | 非空,但为 crossDomain 中转链接,query 仅 `ticket`/`gourl`/`first_domain` | 循环匹配不到任何凭证参数,构造**空 Credential** 仍返回 `DONE`,静默失败(不报错,后续请求游客态) |

crossDomain url 示例(实测):
```
https://passport.biligame.com/x/passport-login/web/crossDomain?ticket=xxxx&gourl=https%3A%2F%2Fwww.bilibili.com&first_domain=.bilibili.com
```
该 url 是 ticket 中转流程,凭证参数不在这里;确认成功响应 cookies 实测含 `SESSDATA` / `bili_jct` / `DedeUserID` / `sid`。

## 接口实测行为

### 轮询接口

- 地址:`login.json` 中 `qrcode.web.get_events`,即 `https://passport.bilibili.com/qrcode/getLoginInfo`(GET)
- 参数:`qrcode_key`(即 `QrCodeLogin` 实例的私有属性 `_QrCodeLogin__qr_key`)

### 响应为两层结构

```jsonc
{
  "code": 0,              // 外层:请求级状态(0 = 请求成功)
  "data": {
    "code": 86090,        // 内层:二维码业务状态(见下表)
    "message": "二维码已扫描",
    "url": "...",         // 确认成功时可能为空——不可依赖
    "refresh_token": "..." // 确认成功时返回,即 ac_time_value
  }
}
```

### 内层 `data.code` 状态码

| code | 含义 |
| --- | --- |
| `86101` | 未扫描 |
| `86090` | 已扫描,等待用户确认 |
| `86038` | 二维码已过期 |
| `0` | 用户已确认登录成功 |

### 确认成功时凭证的位置

- **响应 `Set-Cookie`**(可靠):`SESSDATA`、`bili_jct`、`DedeUserID`
- `data.refresh_token`:凭证续期用的 `ac_time_value`
- `data.url`:crossDomain 链接,**可能为空或仅含参数**,zoku 现有 `check_state` 的字符串解析就是栽在这里

## 我们的工作实现(参考)

不依赖 `check_state`,直接轮询 + 解析:

```python
# 生成二维码(zoku 部分照常)
qr = login_v2.QrCodeLogin(platform=login_v2.QrCodeLoginChannel.WEB)
await qr.generate_qrcode()
qr_key = qr._QrCodeLogin__qr_key

# 轮询状态
resp = await client.request("GET", LOGIN_API["qrcode"]["web"]["get_events"],
                            params={"qrcode_key": qr_key})
events = resp.json()
data = events.get("data") or {}
code = data.get("code")

if code == 86101:      # 未扫
    ...
elif code == 86090:    # 已扫待确认
    ...
elif code == 86038:    # 过期
    ...

# code == 0:确认成功,凭证从响应 Set-Cookie 提取
cookies = resp.cookies
cred = Credential(
    sessdata=str(cookies.get("SESSDATA", "")),
    bili_jct=str(cookies.get("bili_jct", "")),
    dedeuserid=str(cookies.get("DedeUserID", "")),
    ac_time_value=data.get("refresh_token", ""),
)
```

## 对上游的建议

1. **修复 `check_state()` 的凭证提取**:优先从响应 cookies 提取,保留对 `data.url` query 的解析作为兜底;`data.url` 为空时不应抛 `IndexError`;解析不到凭证参数时不应静默返回空凭证的 `DONE`
2. **暴露 `qrcode_key`**:目前是私有属性 `_QrCodeLogin__qr_key`,轮询必须依赖它,建议提供公开属性/方法
3. 文档补充上述状态码与两层响应结构说明

## 附:验证过的完整登录流程

1. `generate_qrcode()` 生成
2. `get_qrcode_picture().content` 拿 PNG 字节
3. 轮询 `get_events` 直到 `data.code == 0`
4. 从响应 cookies 构造 `Credential`(含 `ac_time_value` 支持后续 `refresh()` 续期)
5. 用 `get_self_info(cred)` 验证凭证有效
