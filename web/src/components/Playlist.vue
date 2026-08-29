<script setup>
import { computed, nextTick, ref, watch } from "vue";
import { usePlayerStore } from "../stores/player";
import { formatTime } from "../api";
import DownloadDialog from "./DownloadDialog.vue";

const store = usePlayerStore();
const showDownloadDialog = ref(false);

// 切歌时把当前曲目滚动到可视区域(删除歌曲导致的索引变化不滚动)
const listEl = ref(null);
let lastLength = store.playlist.length;
watch(
  () => store.currentIndex,
  async () => {
    const len = store.playlist.length;
    const shrunk = len < lastLength;
    lastLength = len;
    if (shrunk) return; // 列表缩短 = 删除曲目,不滚动
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
  showMenu.value = false;
  store.clearPlaylist();
}

// ---------------------------------------------------------------- 头部下拉菜单

const showMenu = ref(false);

function onMenuPlayAll() {
  showMenu.value = false;
  store.playAll();
}

function onMenuDownload() {
  showMenu.value = false;
  showDownloadDialog.value = true;
}

// 点击菜单外关闭
window.addEventListener("click", () => (showMenu.value = false));

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

const hoverDetail = ref(null); // { item, x, y } 悬停浮层
const pinnedDetail = ref(null); // { item, x, y } 点击 ℹ 固定浮层(不随鼠标消失)
let detailTimer = null;

function onRowEnter(item, e) {
  clearTimeout(detailTimer);
  const rect = e.currentTarget.getBoundingClientRect();
  // 浮层放在行左侧(主区方向),与行左缘重叠 2px:鼠标左移直接进浮层,
  // 路径上没有其他列表行,不会被相邻行 hover 抢走
  hoverDetail.value = {
    item,
    x: Math.max(8, rect.left - 308),
    y: rect.top,
  };
}

function onRowLeave() {
  clearTimeout(detailTimer);
  detailTimer = setTimeout(() => (hoverDetail.value = null), 600);
}

/** 点击 ℹ:固定浮层(悬停路径点不到时的兜底入口) */
function onPinDetail(item, e) {
  e.stopPropagation();
  clearTimeout(detailTimer);
  const rect = e.currentTarget.closest(".row").getBoundingClientRect();
  pinnedDetail.value = {
    item,
    x: Math.max(8, rect.left - 308),
    y: rect.top,
  };
}

function closePinned() {
  pinnedDetail.value = null;
}

/** 当前显示的详情浮层(固定优先) */
const detail = computed(() => pinnedDetail.value || hoverDetail.value);

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
      <div v-if="store.playlist.length" class="head-actions">
        <button
          class="head-btn menu-btn"
          :class="{ on: showMenu }"
          title="更多操作"
          @click.stop="showMenu = !showMenu"
        >
          ⋯
        </button>
        <Transition name="menu-drop">
          <div v-if="showMenu" class="menu" @click.stop>
            <button class="menu-item" @click="onMenuPlayAll">▶ 播放全部</button>
            <button class="menu-item" @click="onMenuDownload">↓ 下载全部</button>
            <button
              class="menu-item danger"
              :class="{ armed: confirmClear }"
              @click="onClearClick"
            >
              {{ confirmClear ? "确认清空?" : "✕ 清空播放列表" }}
            </button>
          </div>
        </Transition>
      </div>
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
        <button
          class="icon-btn info-btn"
          title="歌曲详情(固定显示)"
          @click.stop="onPinDetail(item, $event)"
        >
          ℹ
        </button>
      </div>
    </div>

    <DownloadDialog
      v-if="showDownloadDialog"
      @close="showDownloadDialog = false"
      @confirm="onDownloadConfirm"
    />

    <!-- 行悬停/固定详情(完整信息 + 替换歌曲) -->
    <div
      v-if="detail"
      class="row-detail"
      :style="{ left: detail.x + 'px', top: detail.y + 'px' }"
      @mouseenter="clearTimeout(detailTimer)"
      @mouseleave="!pinnedDetail && onRowLeave()"
      @click.stop
    >
      <button
        v-if="pinnedDetail"
        class="rd-close"
        title="关闭"
        @click="closePinned"
      >
        ✕
      </button>
      <div class="rd-title">{{ detail.item.track.title }}</div>
      <div class="rd-row">
        <span class="rd-label">UP:</span> {{ detail.item.track.artist || "未知 UP 主" }}
        · {{ formatTime(detail.item.track.duration) }}
      </div>
      <div class="rd-row">
        <span class="rd-label">来源:</span> {{ detail.item.track.source }}
      </div>
      <div
        v-if="detail.item.track.orig_name"
        class="rd-row"
      >
        <span class="rd-label">原曲:</span>
        {{ detail.item.track.orig_name }}
        <template v-if="detail.item.track.orig_artists?.length">
          / {{ detail.item.track.orig_artists.join("、") }}
        </template>
      </div>
      <div class="rd-actions">
        <span
          v-if="detail.item.track.id.startsWith('match:')"
          class="rd-badge"
        >
          待匹配
        </span>
        <button
          class="rd-btn"
          title="以原歌名搜索并替换此曲来源"
          @click="store.startReplace(detail.item.track)"
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
.head-actions {
  position: relative;
  flex-shrink: 0;
}
.menu-btn {
  font-weight: 700;
  letter-spacing: 1px;
}
.menu-btn.on {
  background: var(--accent-soft);
}
.menu {
  position: absolute;
  right: 0;
  top: calc(100% + 6px);
  z-index: 60;
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 150px;
  padding: 6px;
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 10px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.4);
}
.menu-item {
  text-align: left;
  font-size: 12px;
  color: var(--text);
  padding: 7px 10px;
  border-radius: 6px;
}
.menu-item:hover {
  background: var(--hover);
}
.menu-item.danger {
  color: #e56d6d;
}
.menu-item.danger.armed {
  background: #e56d6d;
  color: #fff;
}
.menu-drop-enter-active,
.menu-drop-leave-active {
  transition: opacity 0.15s ease, transform 0.15s ease;
}
.menu-drop-enter-from,
.menu-drop-leave-to {
  opacity: 0;
  transform: translateY(-6px) scale(0.97);
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
.info-btn {
  width: 24px;
  height: 24px;
  font-size: 12px;
  color: var(--text-dim);
  flex-shrink: 0;
  opacity: 0;
  transition: opacity 0.15s;
}
.row:hover .info-btn {
  opacity: 1;
}
.info-btn:hover {
  color: var(--accent);
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
.rd-close {
  position: absolute;
  top: 8px;
  right: 10px;
  font-size: 11px;
  color: var(--text-dim);
  padding: 2px 6px;
}
.rd-close:hover {
  color: #e56d6d;
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
