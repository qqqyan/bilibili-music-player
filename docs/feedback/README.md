# 应用内反馈 · 视觉证据

本目录是「应用内截图反馈直连 GitHub issue」的 PR 视觉证据,由 Playwright + 本机 Chrome
从真实运行的应用中捕获(非设计稿)。

- 基线:`origin/main` @ `351503d`(无反馈入口)
- 改动:本 PR 分支(顶栏新增 🐞 入口与反馈弹窗)
- 场景:空歌单主页,1440×900 视口,深色主题,同一后端
- 日志数据来自本地实际运行的后端(自动脱敏后的最近日志)

| 文件 | 场景 |
| --- | --- |
| `before-home.jpg` | 基线主页,顶栏只有 ⚙ / 🎯 |
| `after-home.jpg` | 改动后主页,顶栏新增 🐞 反馈入口 |
| `after-dialog.jpg` | 反馈弹窗:描述 + 已附截图(自动复制到剪贴板) |
| `after-dialog-logs.jpg` | 展开「查看脱敏后的日志」 |
| `after-submitted.jpg` | 点击提交后:在 GitHub 打开预填 issue,并保存本地诊断包 |

复现:分别启动基线前端(`5174`)与改动后前端(`5173`)到同一后端,再用 Playwright
以 1440×900 截图。提交验证用路由拦截 GitHub,确认实际跳转的是
`https://github.com/qqqyan/bilibili-music-player/issues/new?title=...&body=...`。
