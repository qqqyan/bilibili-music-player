# bilibili-music-player

从 bilibili 获取视频音频的 web 音乐播放器:搜索任何 bilibili 视频,当作音乐播放(带画面的可看 MV),加入播放列表,支持多种播放策略。

## 功能

- **搜索**:全站视频搜索,任何视频都可以听(音频流直出)
- **多音质**:64K / 132K / 192K(登录后可用 Hi-Res / 杜比);视频画质 360P/480P/720P…(登录后更高)
- **MV 模式**:视频条目可切换画面播放(音画同步),音质/画质独立选择
- **播放列表**:持久化到项目目录 `data/playlist.json`,换浏览器不丢
- **本地缓存**(`data/cache/`,音频/视频对称,均为 peer):
  - 每份文件独立保存并带档位标识:`q{音质id}.m4a` + `v{画质id}.mp4`,换档不覆盖
  - **懒下载**:播放过的曲目自动下载(插队优先,音频最高档+视频最高画质);「下载全部」按钮手动批量下载
  - 串行限频下载,任务间/曲目内两个请求之间都有间隔,防触发 bilibili 风控
  - 本地优先播放:音频/视频**独立决策**——各自比较本地最高档与期望档,满足用本地,否则远程(可混合来源)
  - 视频曲目升级旧缓存自动补下画面;远程失败自动回退本地(下架/断网也能听);缓存文件被外部删除自动感知并重下
  - 失败重试 + 播放列表缓存状态图标(✓/↓/◷/!),失败可点击重试
- **播放策略**:
  - 播放模式:顺序播放 / 列表循环 / 单曲循环 / 随机播放
  - 音质切换:保持进度无缝续播,期望音质跨曲目生效
  - CDN 回退:主 CDN 失败自动切换备用节点

## 架构

```
web/            Vue 3 + Vite 前端(播放器 UI)
src/            FastAPI 后端
  ├─ main.py              API 路由(搜索/解析/流代理/缓存)
  ├─ bilibili_client.py   bilibili-api-zoku 封装(搜索、DASH 流解析)
  ├─ stream_proxy.py      CDN 流代理(Range 透传、多 CDN 回退)
  ├─ cache_store.py       本地缓存存储(data/cache/{track_id}/)
  ├─ download_manager.py  限频下载队列(串行、点播优先、失败重试)
  ├─ playlist_store.py    歌单持久化(data/playlist.json)
  └─ config.py            登录凭证加载(.env)
```

后端依赖上游维护版 [bilibili-api-zoku](https://github.com/bromothymolb/bilibili-api-zoku),通过 GitHub archive tarball 固定 commit 安装(绕开 git 协议,国内网络友好;升级时更新 `pyproject.toml` 中的 commit hash)。

## 快速开始

```bash
# 1. 后端(端口 8000)
uv sync
uv run bilibili-music-player

# 2. 前端(端口 5173,dev 模式代理 /api 到后端)
cd web && npm install && npm run dev

# 打开 http://localhost:5173
```

## 登录(可选,获取更高音质)

在项目根目录创建 `.env`(已在 .gitignore 中):

```bash
# 从浏览器 Cookie 获取(bilibili.com 登录后 F12 → Application → Cookies)
BILI_SESSDATA=xxxx
BILI_BILI_JCT=xxxx
BILI_BUVID3=xxxx
BILI_BUVID4=xxxx
BILI_DEDEUSERID=xxxx
```

不配置也能正常使用(匿名,音质上限 192K)。

## 生产模式

```bash
cd web && npm run build     # 产物在 web/dist,后端自动托管
uv run bilibili-music-player
# 直接访问 http://127.0.0.1:8000
```

## 已知限制

- 仅 FLV 流的远古视频不支持播放
- 多 P 视频目前播放 P1,分 P 选择在规划中

## Roadmap

- [ ] 网易云等更多平台搜索
- [ ] 多 P 视频分 P 选择
- [ ] B 站歌单(AudioList)导入
- [ ] 歌词(弹幕转歌词?)
- [ ] 安卓端(Capacitor / uni-app 打包)
