<script setup>
import { onMounted, onUnmounted, ref } from "vue";
import { usePlayerStore } from "../stores/player";
import { formatTime, getUserInfo } from "../api";

const props = defineProps({
  items: { type: Array, default: () => [] },
  loading: Boolean,
  hasMore: Boolean,
  error: String,
  replaceMode: Boolean, // 替换歌曲上下文激活时显示 ⇄ 按钮
});
const emit = defineEmits(["play", "add", "replace", "loadMore", "open-user"]);

const store = usePlayerStore();

function isCurrent(track) {
  return store.currentTrack?.id === track.id;
}

// 无限滚动:哨兵进入视口自动加载更多(父级负责防抖)
const sentinel = ref(null);
let observer = null;

onMounted(() => {
  observer = new IntersectionObserver((entries) => {
    if (entries[0]?.isIntersecting) emit("loadMore");
  });
  if (sentinel.value) observer.observe(sentinel.value);
});
onUnmounted(() => observer?.disconnect());

// UP 主悬停预览:悬停 20ms 后拉取信息显示浮层（感觉20够了，体验上挺好的）
const hoverUser = ref(null); // { trackId, mid, info }
let hoverTimer = null;

function onArtistEnter(track) {
  if (!track.mid) return;
  clearTimeout(hoverTimer);
  hoverTimer = setTimeout(async () => {
    try {
      const info = await getUserInfo(track.mid);
      if (hoverUser.value?.trackId === track.id) return;
      hoverUser.value = { trackId: track.id, mid: track.mid, info };
    } catch {
      /* 静默 */
    }
  }, 20);
}

function onArtistLeave() {
  clearTimeout(hoverTimer);
  hoverUser.value = null;
}
</script>

<template>
  <div class="results">
    <div v-if="error" class="hint error">{{ error }}</div>
    <div v-else-if="!items.length && !loading" class="hint">
      搜索你想听的视频——任何 bilibili 视频都可以当作音乐播放,带画面的还能看 MV
    </div>

    <div v-if="items.length" class="list">
      <div
        v-for="track in items"
        :key="track.id"
        class="item"
        :class="{ current: isCurrent(track) }"
        @click="emit('play', track)"
        @mouseleave="onArtistLeave"
      >
        <div class="cover-box">
          <img class="cover" :src="track.cover" loading="lazy" alt="" />
          <span class="duration">{{ formatTime(track.duration) }}</span>
          <span class="play-arrow">▶</span>
        </div>
        <div class="meta">
          <div class="title ellipsis">{{ track.title }}</div>
          <div class="sub ellipsis">
            <span
              class="artist"
              :class="{ clickable: track.mid }"
              :title="track.mid ? '悬停查看 UP 主信息,点击进入主页' : ''"
              @mouseenter="onArtistEnter(track)"
              @click.stop="track.mid && emit('open-user', track.mid)"
            >
              {{ track.artist || "未知 UP 主" }}
            </span>
            <span class="dot">·</span>
            <span>{{ track.source }}</span>
          </div>
        </div>
        <!-- 悬停预览浮层(item 级定位,避免被 .sub 的 overflow:hidden 裁剪) -->
        <span
          v-if="hoverUser?.trackId === track.id && hoverUser.info"
          class="hover-card"
          @click.stop="emit('open-user', track.mid)"
        >
          <img
            class="hc-face"
            :src="hoverUser.info.face"
            alt=""
            title="点击进入 UP 主页"
          />
          <span class="hc-meta">
            <span class="hc-name">{{ hoverUser.info.name }}</span>
            <span class="hc-fans">
              粉丝 {{ (hoverUser.info.fans ?? 0).toLocaleString() }}
            </span>
            <span class="hc-sign ellipsis">
              {{ hoverUser.info.sign || "这个人很懒,什么都没写" }}
            </span>
          </span>
        </span>
        <button
          class="icon-btn add-btn"
          :title="'加入播放列表'"
          @click.stop="emit('add', track)"
        >
          +
        </button>
        <button
          v-if="replaceMode"
          class="icon-btn replace-btn"
          title="替换歌曲"
          @click.stop="emit('replace', track)"
        >
          ⇄
        </button>
      </div>
    </div>

    <!-- 滚动哨兵:进入视口自动加载(无限滚动) -->
    <div v-if="hasMore" ref="sentinel" class="sentinel"></div>
    <div v-if="hasMore" class="load-more">
      <button class="load-btn" :disabled="loading" @click="emit('loadMore')">
        {{ loading ? "加载中…" : "加载更多" }}
      </button>
    </div>
    <div v-else-if="items.length" class="load-more dim">没有更多了</div>
  </div>
</template>

<style scoped>
.results {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.hint {
  padding: 48px 16px;
  text-align: center;
  color: var(--text-dim);
  line-height: 1.8;
}
.hint.error {
  color: #e56d6d;
}
.list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.item {
  position: relative; /* 悬停预览浮层的定位参考 */
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px;
  border-radius: 10px;
  cursor: pointer;
  transition: background 0.15s;
}
.item:hover {
  background: var(--hover);
}
.item.current {
  background: var(--accent-soft);
}
.cover-box {
  position: relative;
  flex-shrink: 0;
  width: 108px;
  height: 60px;
  border-radius: 6px;
  overflow: hidden;
  background: #000;
}
.cover {
  width: 100%;
  height: 100%;
  object-fit: cover;
  opacity: 0.9;
}
.duration {
  position: absolute;
  right: 4px;
  bottom: 4px;
  padding: 1px 5px;
  border-radius: 4px;
  background: rgba(0, 0, 0, 0.7);
  font-size: 11px;
}
.play-arrow {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 20px;
  color: #fff;
  background: rgba(0, 0, 0, 0.35);
  opacity: 0;
  transition: opacity 0.15s;
}
.item:hover .play-arrow {
  opacity: 1;
}
.meta {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.title {
  font-size: 14px;
}
.sub {
  font-size: 12px;
  color: var(--text-dim);
  display: flex;
  align-items: center;
  gap: 6px;
}
.artist {
  color: var(--accent);
  position: relative;
}
.artist.clickable {
  cursor: pointer;
}
.artist.clickable:hover {
  text-decoration: underline;
}
.dot {
  opacity: 0.5;
}
/* 悬停预览浮层 */
.hover-card {
  position: absolute;
  bottom: 100%; /* 贴住整行顶部,不留空隙(方便鼠标移入) */
  left: 128px; /* 对齐 meta 区左缘(8 padding + 108 封面 + 12 gap) */
  z-index: 60;
  display: flex;
  gap: 10px;
  width: 260px;
  padding: 12px;
  border-radius: 10px;
  background: var(--panel-2);
  border: 1px solid var(--border);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.45);
  color: var(--text);
  text-decoration: none;
  cursor: pointer;
}
/* 不可见的「桥」:覆盖卡片与名字之间的过渡区,鼠标移入卡片时不移出 item */
.hover-card::before {
  content: "";
  position: absolute;
  top: 100%;
  left: 0;
  right: 0;
  height: 8px;
}
.hc-face {
  width: 48px;
  height: 48px;
  border-radius: 50%;
  object-fit: cover;
  flex-shrink: 0;
  cursor: pointer;
}
.hc-meta {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
  flex: 1;
}
.hc-name {
  font-size: 14px;
  font-weight: 600;
}
.hc-fans {
  font-size: 11px;
  color: var(--text-dim);
}
.hc-sign {
  font-size: 11px;
  color: var(--text-dim);
  max-width: 180px;
}
.add-btn {
  flex-shrink: 0;
  font-size: 20px;
  font-weight: 300;
}
.replace-btn {
  flex-shrink: 0;
  font-size: 15px;
  color: var(--accent);
  border: 1px solid var(--accent);
  border-radius: 6px;
  padding: 2px 6px;
}
.sentinel {
  height: 2px;
}
.load-more {
  text-align: center;
  padding: 8px 0 16px;
}
.load-more.dim {
  color: var(--text-dim);
  font-size: 12px;
}
.load-btn {
  padding: 6px 24px;
  border-radius: 16px;
  border: 1px solid var(--border);
  color: var(--text-dim);
  transition: all 0.15s;
}
.load-btn:hover:not(:disabled) {
  color: var(--accent);
  border-color: var(--accent);
}
.load-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>
