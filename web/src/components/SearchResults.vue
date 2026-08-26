<script setup>
import { usePlayerStore } from "../stores/player";
import { formatTime } from "../api";

defineProps({
  items: { type: Array, default: () => [] },
  loading: Boolean,
  hasMore: Boolean,
  error: String,
});
const emit = defineEmits(["play", "add", "loadMore"]);

const store = usePlayerStore();

function isCurrent(track) {
  return store.currentTrack?.id === track.id;
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
      >
        <div class="cover-box">
          <img class="cover" :src="track.cover" loading="lazy" alt="" />
          <span class="duration">{{ formatTime(track.duration) }}</span>
          <span class="play-arrow">▶</span>
        </div>
        <div class="meta">
          <div class="title ellipsis">{{ track.title }}</div>
          <div class="sub ellipsis">
            <span class="artist">{{ track.artist || "未知 UP 主" }}</span>
            <span class="dot">·</span>
            <span>{{ track.source }}</span>
          </div>
        </div>
        <button
          class="icon-btn add-btn"
          :title="'加入播放列表'"
          @click.stop="emit('add', track)"
        >
          +
        </button>
      </div>
    </div>

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
}
.dot {
  opacity: 0.5;
}
.add-btn {
  flex-shrink: 0;
  font-size: 20px;
  font-weight: 300;
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
