<script setup>
import { computed, nextTick, ref, watch } from "vue";
import { usePlayerStore } from "../stores/player";
import { formatTime } from "../api";
import DownloadDialog from "./DownloadDialog.vue";

const store = usePlayerStore();
const showDownloadDialog = ref(false);

// 切歌时把当前曲目滚动到可视区域
const listEl = ref(null);
watch(
  () => store.currentIndex,
  async () => {
    await nextTick();
    const el = listEl.value?.querySelector(".row.current");
    el?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }
);

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

// 清空二次确认:首次点击进入待确认态(4s 后自动复原),再点才执行
const confirmClear = ref(false);
let clearTimer = null;
function onClearClick() {
  if (!confirmClear.value) {
    confirmClear.value = true;
    clearTimer = setTimeout(() => (confirmClear.value = false), 4000);
    return;
  }
  clearTimeout(clearTimer);
  confirmClear.value = false;
  store.clearPlaylist();
}

// ---------------------------------------------------------------- 悬停详情
// featureList #6:行悬停显示完整信息(fixed 定位规避 .list overflow 裁剪),
// 附带「替换歌曲」入口;封面加载失败回退音符占位图。
const NOTE_SVG =
  "data:image/svg+xml;utf8," +
  encodeURIComponent(
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">' +
      '<rect width="24" height="24" fill="#2a2a33"/>' +
      '<path fill="#8a8a99" d="M9 18V6l9-2v12"/>' +
      '<circle cx="6.5" cy="18" r="2.5" fill="#8a8a99"/>' +
      '<circle cx="15.5" cy="16" r="2.5" fill="#8a8a99"/></svg>'
  );

function onCoverError(e) {
  if (!e.target.src.startsWith("data:")) e.target.src = NOTE_SVG;
}

const hoverDetail = ref(null); // { item, x, y }
let detailTimer = null;

function onRowEnter(item, e) {
  clearTimeout(detailTimer);
  const rect = e.currentTarget.getBoundingClientRect();
  hoverDetail.value = {
    item,
    x: Math.max(8, rect.left - 316),
    y: Math.min(rect.top, window.innerHeight - 280),
  };
}

function onRowLeave() {
  clearTimeout(detailTimer);
  detailTimer = setTimeout(() => (hoverDetail.value = null), 200);
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
        :class="{ armed: confirmClear }"
        :title="confirmClear ? '再点一次确认清空' : '清空播放列表'"
        @click="onClearClick"
      >
        {{ confirmClear ? "确认清空?" : "清空" }}
      </button>
    </div>

    <div v-if="!store.playlist.length" class="empty">
      还没有歌曲
      <br />
      搜索并点击「+」加入列表
    </div>

    <div v-else ref="listEl" class="list">
      <div
        v-for="item in filtered"
        :key="item.track.id"
        class="row"
        :class="{ current: item.index === store.currentIndex }"
        @click="store.playTrack(item.index)"
        @mouseenter="onRowEnter(item, $event)"
        @mouseleave="onRowLeave"
      >
        <span class="idx">{{ item.index === store.currentIndex ? "♪" : item.index + 1 }}</span>
        <img class="thumb" :src="item.track.cover || NOTE_SVG" alt="" @error="onCoverError" />
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

    <!-- 行悬停详情(完整信息 + 替换歌曲) -->
    <div
      v-if="hoverDetail"
      class="row-detail"
      :style="{ left: hoverDetail.x + 'px', top: hoverDetail.y + 'px' }"
      @mouseenter="clearTimeout(detailTimer)"
      @mouseleave="onRowLeave"
      @click.stop
    >
      <div class="rd-title">{{ hoverDetail.item.track.title }}</div>
      <div class="rd-row">
        <span class="rd-label">UP:</span> {{ hoverDetail.item.track.artist || "未知 UP 主" }}
        · {{ formatTime(hoverDetail.item.track.duration) }}
      </div>
      <div class="rd-row">
        <span class="rd-label">来源:</span> {{ hoverDetail.item.track.source }}
      </div>
      <div
        v-if="hoverDetail.item.track.orig_name"
        class="rd-row"
      >
        <span class="rd-label">原曲:</span>
        {{ hoverDetail.item.track.orig_name }}
        <template v-if="hoverDetail.item.track.orig_artists?.length">
          / {{ hoverDetail.item.track.orig_artists.join("、") }}
        </template>
      </div>
      <div class="rd-actions">
        <span
          v-if="hoverDetail.item.track.id.startsWith('match:')"
          class="rd-badge"
        >
          待匹配
        </span>
        <button
          class="rd-btn"
          title="以原歌名搜索并替换此曲来源"
          @click="store.startReplace(hoverDetail.item.track)"
        >
          替换歌曲
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.playlist {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
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
.clear-btn.armed {
  color: #fff;
  background: #e56d6d;
}
.clear-btn.armed:hover {
  color: #fff;
  background: #c94f4f;
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

/* 行悬停详情 */
.row-detail {
  position: fixed;
  z-index: 70;
  width: 300px;
  padding: 12px 14px;
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 10px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.45);
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 12px;
  line-height: 1.6;
}
.rd-title {
  font-size: 13px;
  font-weight: 600;
  white-space: normal;
  word-break: break-all;
}
.rd-row {
  color: var(--text-dim);
}
.rd-label {
  color: var(--text);
}
.rd-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 4px;
}
.rd-badge {
  font-size: 11px;
  color: #e5a96d;
  border: 1px solid #e5a96d;
  border-radius: 8px;
  padding: 1px 8px;
}
.rd-btn {
  padding: 4px 12px;
  border-radius: 12px;
  border: 1px solid var(--accent);
  color: var(--accent);
  font-size: 12px;
}
.rd-btn:hover {
  background: var(--accent-soft);
}
</style>
