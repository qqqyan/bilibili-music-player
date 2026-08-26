<script setup>
import { usePlayerStore } from "../stores/player";
import { formatTime } from "../api";

const store = usePlayerStore();

function cacheState(track) {
  return store.cacheStatus[track.id] || { state: "none", local_qualities: [] };
}
</script>

<template>
  <div class="playlist">
    <div class="head">
      <span class="head-title">播放列表</span>
      <span class="count">{{ store.playlist.length }} 首</span>
      <button
        v-if="store.playlist.length"
        class="head-btn"
        title="下载全部未缓存曲目到本地"
        @click="store.downloadAll()"
      >
        下载全部
      </button>
      <button
        v-if="store.playlist.length"
        class="clear-btn"
        title="清空播放列表"
        @click="store.clearPlaylist()"
      >
        清空
      </button>
    </div>

    <div v-if="!store.playlist.length" class="empty">
      还没有歌曲
      <br />
      搜索并点击「+」加入列表
    </div>

    <div v-else class="list">
      <div
        v-for="(track, i) in store.playlist"
        :key="track.id"
        class="row"
        :class="{ current: i === store.currentIndex }"
        @click="store.playTrack(i)"
      >
        <span class="idx">{{ i === store.currentIndex ? "♪" : i + 1 }}</span>
        <img class="thumb" :src="track.cover" alt="" />
        <div class="meta">
          <div class="title ellipsis">{{ track.title }}</div>
          <div class="artist ellipsis">{{ track.artist || "未知 UP 主" }}</div>
        </div>
        <span class="dur">{{ formatTime(track.duration) }}</span>
        <span
          v-if="cacheState(track).state === 'failed'"
          class="cache-icon failed"
          title="下载失败,点击重试"
          @click.stop="store.retryDownload(track.id)"
        >
          !
        </span>
        <span
          v-else-if="cacheState(track).state === 'downloading'"
          class="cache-icon downloading"
          title="下载中"
        >
          ↓
        </span>
        <span
          v-else-if="cacheState(track).state === 'pending'"
          class="cache-icon pending"
          title="等待下载"
        >
          ◷
        </span>
        <span
          v-else-if="cacheState(track).state === 'done'"
          class="cache-icon done"
          title="已缓存到本地"
        >
          ✓
        </span>
        <button
          class="icon-btn del-btn"
          title="从列表移除"
          @click.stop="store.removeTrack(i)"
        >
          ✕
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.playlist {
  display: flex;
  flex-direction: column;
  height: 100%;
}
.head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 14px 16px 10px;
  border-bottom: 1px solid var(--border);
}
.head-title {
  font-weight: 600;
}
.count {
  color: var(--text-dim);
  font-size: 12px;
}
.clear-btn {
  margin-left: auto;
  font-size: 12px;
  color: var(--text-dim);
  padding: 4px 8px;
  border-radius: 6px;
}
.clear-btn:hover {
  color: #e56d6d;
  background: var(--hover);
}
.head-btn {
  font-size: 12px;
  color: var(--accent);
  padding: 4px 8px;
  border-radius: 6px;
}
.head-btn:hover {
  background: var(--accent-soft);
}
.empty {
  padding: 48px 16px;
  text-align: center;
  color: var(--text-dim);
  line-height: 2;
}
.list {
  flex: 1;
  overflow-y: auto;
  padding: 6px;
}
.row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px;
  border-radius: 8px;
  cursor: pointer;
  transition: background 0.15s;
}
.row:hover {
  background: var(--hover);
}
.row.current {
  background: var(--accent-soft);
}
.idx {
  width: 22px;
  text-align: center;
  color: var(--text-dim);
  font-size: 12px;
  flex-shrink: 0;
}
.row.current .idx {
  color: var(--accent);
}
.thumb {
  width: 44px;
  height: 44px;
  border-radius: 6px;
  object-fit: cover;
  flex-shrink: 0;
}
.meta {
  flex: 1;
  min-width: 0;
}
.title {
  font-size: 13px;
}
.artist {
  font-size: 11px;
  color: var(--text-dim);
  margin-top: 2px;
}
.dur {
  font-size: 11px;
  color: var(--text-dim);
  flex-shrink: 0;
}
.del-btn {
  width: 24px;
  height: 24px;
  font-size: 11px;
  flex-shrink: 0;
  opacity: 0;
  transition: opacity 0.15s;
}
.row:hover .del-btn {
  opacity: 1;
}
.cache-icon {
  width: 18px;
  text-align: center;
  font-size: 12px;
  flex-shrink: 0;
}
.cache-icon.done {
  color: #6fd08c;
}
.cache-icon.downloading,
.cache-icon.pending {
  color: var(--text-dim);
}
.cache-icon.failed {
  color: #e56d6d;
  cursor: pointer;
  font-weight: 700;
}
</style>
