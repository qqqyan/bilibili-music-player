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

/** 解析曲目播放流,kind: video | audio,id: bv... / au... */
export function resolveTrack(kind, id) {
  return request(`/api/resolve/${kind}/${id}`);
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

/** 批量加入下载队列(priority=true 时插队优先下载) */
export async function queueCache(trackIds, priority = false) {
  const res = await fetch("/api/cache/queue", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ track_ids: trackIds, priority }),
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
