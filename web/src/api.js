// 后端 API 封装

async function request(path) {
  const res = await fetch(path);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || detail;
    } catch {
      /* 忽略非 JSON 错误体 */
    }
    throw new Error(detail);
  }
  return res.json();
}

/** 搜索视频(全站),返回 SearchPage */
export function searchTracks(keyword, page = 1) {
  return request(`/api/search?keyword=${encodeURIComponent(keyword)}&page=${page}`);
}

/** 解析 bilibili 视频播放流(id: bvBVxxx) */
export function resolveTrack(id) {
  return request(`/api/resolve/${id}`);
}

/** 搜索 UP 主 */
export function searchUsers(keyword, page = 1) {
  return request(`/api/users/search?keyword=${encodeURIComponent(keyword)}&page=${page}`);
}

/** UP 主主页:信息 + 投稿视频(分页) */
export function getUserProfile(mid, page = 1) {
  return request(`/api/user/${mid}?page=${page}`);
}

/** UP 主信息(轻量,悬停预览用) */
export function getUserInfo(mid) {
  return request(`/api/user/${mid}/info`);
}

/** 播放决策接口:合并档位列表 + 播放来源决策 + 补缓存决策 */
export function trackPlan(id, { audioQuality = -1, videoQuality = -1 } = {}) {
  return request(
    `/api/track/${id}/plan?audio_quality=${audioQuality}&video_quality=${videoQuality}`
  );
}

/** 统一播放端点(后端路由本地/在线,前端无需感知来源) */
export function playUrl(id, kind, qualityId) {
  return `/api/play/${id}?kind=${kind}&quality_id=${qualityId}`;
}

/** 获取歌单(后端项目目录持久化) */
export function getPlaylist() {
  return request("/api/playlist");
}

/** 覆盖式保存歌单 */
export async function savePlaylist(items) {
  const res = await fetch("/api/playlist", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(items),
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail || detail;
    } catch {
      /* 忽略非 JSON 错误体 */
    }
    throw new Error(detail);
  }
  return res.json();
}

/** 批量加入下载队列
 *  priority: 插队;force: 跳过缓存检查;
 *  desired_audio/video_quality: 期望档位(-1=最高,曲目没有该档自动降级) */
export async function queueCache(
  trackIds,
  { priority = false, force = false, desired_audio = -1, desired_video = -1 } = {}
) {
  const res = await fetch("/api/cache/queue", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      track_ids: trackIds,
      priority,
      force,
      desired_audio_quality: desired_audio,
      desired_video_quality: desired_video,
    }),
  });
  if (!res.ok) throw new Error(`入队失败: ${res.statusText}`);
  return res.json();
}

/** 单曲缓存状态 */
export function getCacheStatus(trackId) {
  return request(`/api/cache/status/${trackId}`);
}

/** 全部缓存状态(含总大小) */
export function getAllCache() {
  return request("/api/cache");
}

/** 本地缓存文件的播放地址 */
export function localStreamUrl(trackId, qualityId) {
  return `/api/local/${trackId}?quality_id=${qualityId}`;
}

/** 本地缓存视频画面的播放地址 */
export function localVideoUrl(trackId, qualityId) {
  return `/api/local/${trackId}/video?quality_id=${qualityId}`;
}

/** 登录状态 */
export function authStatus() {
  return request("/api/auth/status");
}

/** 生成登录二维码(返回 session_id 与 PNG data URL) */
export async function authQrcode() {
  const res = await fetch("/api/auth/qrcode", { method: "POST" });
  if (!res.ok) throw new Error(`生成二维码失败: ${res.statusText}`);
  return res.json();
}

/** 轮询二维码登录状态 */
export function authQrcodeStatus(sessionId) {
  return request(`/api/auth/qrcode/status/${sessionId}`);
}

/** 登出 */
export async function authLogout() {
  const res = await fetch("/api/auth/logout", { method: "POST" });
  if (!res.ok) throw new Error(`登出失败: ${res.statusText}`);
  return res.json();
}

/** 密码登录第一步:创建极验验证页(返回内嵌用 URL) */
export async function passwordPrepare() {
  const res = await fetch("/api/auth/password/prepare", { method: "POST" });
  if (!res.ok) throw new Error(`创建验证码失败: ${res.statusText}`);
  return res.json();
}

/** 轮询人机验证是否完成 */
export function passwordGeetestStatus(sessionId) {
  return request(`/api/auth/password/geetest-status/${sessionId}`);
}

/** 密码登录第二步:人机验证完成后提交账号密码 */
export async function passwordLogin(form) {
  const res = await fetch("/api/auth/password", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(form),
  });
  let body = {};
  try {
    body = await res.json();
  } catch {
    /* 忽略非 JSON 错误体 */
  }
  if (!res.ok) throw new Error(body.detail || `登录失败: ${res.statusText}`);
  return body;
}

/** 手动填写凭证登录(从浏览器 Cookie 复制) */
export async function authCredential(form) {
  const res = await fetch("/api/auth/credential", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(form),
  });
  let body = {};
  try {
    body = await res.json();
  } catch {
    /* 忽略非 JSON 错误体 */
  }
  if (!res.ok) throw new Error(body.detail || `登录失败: ${res.statusText}`);
  return body;
}

/** 可选档位列表(后端唯一事实来源) */
export function getQualities() {
  return request("/api/qualities");
}

/** 应用设置 */
export function getSettings() {
  return request("/api/settings");
}

/** 合并保存设置(只更新传入字段) */
export async function saveSettings(patch) {
  const res = await fetch("/api/settings", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  if (!res.ok) throw new Error(`保存设置失败: ${res.statusText}`);
  return res.json();
}

/** 清空全部本地缓存 */
export async function clearCache() {
  const res = await fetch("/api/cache", { method: "DELETE" });
  if (!res.ok) throw new Error(`清空失败: ${res.statusText}`);
  return res.json();
}

/** 遍历全部缓存,每首只保留音频/视频最高档 */
export async function cleanupCache() {
  const res = await fetch("/api/cache/cleanup", { method: "POST" });
  if (!res.ok) throw new Error(`清理失败: ${res.statusText}`);
  return res.json();
}

/** 删除单曲缓存 */
export async function deleteCacheTrack(trackId) {
  const res = await fetch(`/api/cache/${trackId}`, { method: "DELETE" });
  if (!res.ok) throw new Error(`删除失败: ${res.statusText}`);
  return res.json();
}

/** 格式化秒数为 m:ss / h:mm:ss */
export function formatTime(secs) {
  if (!Number.isFinite(secs) || secs < 0) return "0:00";
  secs = Math.floor(secs);
  const h = Math.floor(secs / 3600);
  const m = Math.floor((secs % 3600) / 60);
  const s = secs % 60;
  const mm = h > 0 ? String(m).padStart(2, "0") : String(m);
  return `${h > 0 ? h + ":" : ""}${mm}:${String(s).padStart(2, "0")}`;
}

// ---------------------------------------------------------------- 歌单匹配

/** POST JSON 辅助(与现有手写 fetch 同约定:错误体取 detail) */
async function postJson(path, body) {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  let data = {};
  try {
    data = await res.json();
  } catch {
    /* 忽略非 JSON 错误体 */
  }
  if (!res.ok) throw new Error(data.detail || res.statusText);
  return data;
}

/** 当前匹配任务(summary=true 返回轻量字典,轮询用) */
export function getMatchJob(summary = false) {
  return request(`/api/match/job${summary ? "?summary=true" : ""}`);
}

/** 导入歌单(网易云 JSON 或匹配结果 JSONL,自动识别;覆盖式) */
export function importMatch(name, content, sourcePlatform = "netease") {
  return postJson("/api/match/import", {
    name,
    content,
    source_platform: sourcePlatform,
  });
}

export function matchStart() {
  return postJson("/api/match/start", {});
}

export function matchPause() {
  return postJson("/api/match/pause", {});
}

export function matchResume() {
  return postJson("/api/match/resume", {});
}

export function matchReset() {
  return postJson("/api/match/reset", {});
}

/** 人工选择候选(bvid=null 标记无匹配) */
export function matchChoose(neteaseId, bvid) {
  return postJson("/api/match/choose", { netease_id: neteaseId, bvid });
}

/** 批量把选中歌曲的候选加入播放列表 */
export function matchApply(neteaseIds) {
  return postJson("/api/match/apply", { netease_ids: neteaseIds });
}

/** 把任务歌曲以占位条目加入播放列表(neteaseIds 省略 = 全部) */
export function placeholderAdd(neteaseIds = null) {
  return postJson("/api/match/placeholder", { netease_ids: neteaseIds });
}
