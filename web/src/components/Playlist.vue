<script setup>
import { computed, ref } from "vue";
import { usePlayerStore } from "../stores/player";
import { formatTime } from "../api";
import DownloadDialog from "./DownloadDialog.vue";

const store = usePlayerStore();
const showDownloadDialog = ref(false);

// 列表内搜索:匹配歌曲名 + UP 主名(保留原始索引供播放)
const filterText = ref("");
const filtered = computed(() => {
  const kw = filterText.value.trim().toLowerCase();
  const items = store.playlist.map((track, index) => ({ track, index }));
  if (!kw) return items;
  return items.filter(
    ({ track }) =>
      track.title.toLowerCase().includes(kw) ||
      (track.artist || "").toLowerCase().includes(kw)
  );
});

function cacheState(track) {
  return store.cacheStatus[track.id] || { state: "none", local_qualities: [] };
}

async function onDownloadConfirm({ audio, video }) {
  showDownloadDialog.value = false;
  await store.downloadAll(audio, video);
}
</script>

<template>
  <div class="playlist">
    <div class="head">
      <span class="head-title">播放列表</span>
      <span class="count">{{ store.playlist.length }} 首</span>
      <input
        v-if="store.playlist.length"
        v-model="filterText"
        class="filter-input"
        type="text"
        placeholder="搜索歌曲 / UP 主"
      />
      <button
        v-if="store.playlist.length"
        class="head-btn"
        title="按所选档位下载全部曲目(缺档自动降级)"
        @click="showDownloadDialog = true"
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
        v-for="item in filtered"
        :key="item.track.id"
        class="row"
        :class="{ current: item.index === store.currentIndex }"
        @click="store.playTrack(item.index)"
      >
        <span class="idx">{{ item.index === store.currentIndex ? "♪" : item.index + 1 }}</span>
        <img class="thumb" :src="item.track.cover" alt="" />
        <div class="meta">
          <div class="title ellipsis">{{ item.track.title }}</div>
          <div class="artist ellipsis">{{ item.track.artist || "未知 UP 主" }}</div>
        </div>
        <span class="dur">{{ formatTime(item.track.duration) }}</span>
        <span
          v-if="cacheState(item.track).state === 'failed'"
          class="cache-icon failed"
          title="下载失败,点击重试"
          @click.stop="store.retryDownload(item.track.id)"
        >
          !
        </span>
        <span
          v-else-if="cacheState(item.track).state === 'checking'"
          class="cache-icon checking"
          title="检查档位中"
        >
          ⟳
        </span>
        <span
          v-else-if="cacheState(item.track).state === 'downloading'"
          class="cache-icon downloading"
          title="下载中"
        >
          ↓
        </span>
        <span
          v-else-if="cacheState(item.track).state === 'pending'"
          class="cache-icon pending"
          title="等待下载"
        >
          ◷
        </span>
        <span
          v-else-if="cacheState(item.track).state === 'done'"
          class="cache-icon done"
          title="已缓存到本地"
        >
          ✓
        </span>
        <button
          class="icon-btn del-btn"
          title="从列表移除"
          @click.stop="store.removeTrack(item.index)"
        >
          ✕
        </button>
      </div>
    </div>

    <DownloadDialog
      v-if="showDownloadDialog"
      @close="showDownloadDialog = false"
      @confirm="onDownloadConfirm"
    />
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
.filter-input {
  flex: 1;
  min-width: 0;
  height: 26px;
  padding: 0 10px;
  border-radius: 13px;
  border: 1px solid var(--border);
  background: var(--panel-2);
  outline: none;
  font-size: 12px;
}
.filter-input:focus {
  border-color: var(--accent);
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
.cache-icon.checking {
  color: #6fb1e5;
  animation: checking-spin 1s linear infinite;
  display: inline-block;
}
@keyframes checking-spin {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}
.cache-icon.failed {
  color: #e56d6d;
  cursor: pointer;
  font-weight: 700;
}
</style>
