<script setup>
import { computed, ref } from "vue";
import { MODES, usePlayerStore } from "../stores/player";
import { formatTime } from "../api";

const store = usePlayerStore();

// 进度条拖动状态:拖动中显示拖拽值,松手才提交
const scrubbing = ref(false);
const scrubTime = ref(0);
const displayTime = computed(() => (scrubbing.value ? scrubTime.value : store.currentTime));
const progressPct = computed(() =>
  store.duration > 0 ? Math.min(100, (displayTime.value / store.duration) * 100) : 0
);

function onScrub(e) {
  scrubbing.value = true;
  scrubTime.value = Number(e.target.value);
}
function onScrubEnd(e) {
  scrubbing.value = false;
  store.seek(Number(e.target.value));
}

function cycleMode() {
  const idx = MODES.findIndex((m) => m.id === store.mode);
  store.setMode(MODES[(idx + 1) % MODES.length].id);
}

const currentMode = computed(() => MODES.find((m) => m.id === store.mode));
const volumePct = computed(() => store.volume * 100);

function onQualityChange(e) {
  store.setQuality(Number(e.target.value));
}
function onVideoQualityChange(e) {
  store.setVideoQuality(Number(e.target.value));
}
</script>

<template>
  <div class="player">
    <!-- 左:曲目信息 -->
    <div class="track-info">
      <img
        v-if="store.currentTrack"
        class="cover"
        :src="store.currentTrack.cover"
        alt=""
      />
      <div v-else class="cover placeholder">♪</div>
      <div class="meta">
        <div class="title ellipsis">
          {{ store.currentTrack?.title || "未在播放" }}
        </div>
        <div class="artist ellipsis">
          {{ store.currentTrack?.artist || "搜索视频,点击即可播放" }}
        </div>
      </div>
      <div v-if="store.error" class="error" title="点击关闭" @click="store.error = ''">
        ⚠ {{ store.error }}
      </div>
    </div>

    <!-- 中:控制与进度 -->
    <div class="center">
      <div class="controls">
        <button
          class="icon-btn mode-btn"
          :class="{ active: true }"
          :title="`播放模式:${currentMode?.label}(点击切换)`"
          @click="cycleMode"
        >
          {{ currentMode?.icon }}
        </button>
        <button class="icon-btn" title="上一首" @click="store.prev()">⏮</button>
        <button class="play-btn" :title="store.playing ? '暂停' : '播放'" @click="store.toggle()">
          {{ store.playing ? "⏸" : "▶" }}
        </button>
        <button class="icon-btn" title="下一首" @click="store.next()">⏭</button>
        <button
          class="icon-btn"
          :class="{ active: store.mvEnabled }"
          :title="store.mvEnabled ? 'MV 模式已开启(点击关闭)' : '开启 MV 模式(后续播放持续显示画面)'"
          @click="store.toggleMv()"
        >
          MV
        </button>
        <select
          v-if="store.resolved?.audio_streams?.length"
          class="quality"
          :value="store.qualityIndex"
          title="音质"
          @change="onQualityChange"
        >
          <option :value="-1">自动(最高)</option>
          <option
            v-for="(s, i) in store.resolved.audio_streams"
            :key="s.quality_id"
            :value="i"
          >
            {{ s.quality }}{{ s.local ? "·本地" : "" }}
          </option>
        </select>
        <select
          v-if="store.resolved?.video_streams?.length"
          class="quality"
          :value="store.videoIndex"
          title="画质"
          @change="onVideoQualityChange"
        >
          <option :value="-1">画面自动(最高)</option>
          <option
            v-for="(s, i) in store.resolved.video_streams"
            :key="s.quality_id"
            :value="i"
          >
            {{ s.quality }}{{ s.local ? "·本地" : "" }}
          </option>
        </select>
      </div>

      <div class="progress-row">
        <span class="time">{{ formatTime(displayTime) }}</span>
        <input
          class="range-slider progress"
          type="range"
          min="0"
          :max="Math.max(store.duration, 1)"
          step="1"
          :value="displayTime"
          :style="{ '--pct': progressPct + '%' }"
          :disabled="!store.currentTrack"
          @input="onScrub"
          @change="onScrubEnd"
        />
        <span class="time">{{ formatTime(store.duration) }}</span>
      </div>
    </div>

    <!-- 右:音量 -->
    <div class="volume">
      <span class="vol-icon">🔊</span>
      <input
        class="range-slider vol-slider"
        type="range"
        min="0"
        max="1"
        step="0.01"
        :value="store.volume"
        :style="{ '--pct': volumePct + '%' }"
        @input="store.setVolume(Number($event.target.value))"
      />
    </div>
  </div>
</template>

<style scoped>
.player {
  position: relative;
  display: grid;
  grid-template-columns: minmax(220px, 1fr) minmax(320px, 2fr) minmax(120px, 1fr);
  align-items: center;
  gap: 20px;
}

.track-info {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
}
.cover {
  width: 46px;
  height: 46px;
  border-radius: 8px;
  object-fit: cover;
  flex-shrink: 0;
}
.cover.placeholder {
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--panel-2);
  color: var(--text-dim);
  font-size: 18px;
}
.meta {
  min-width: 0;
}
.title {
  font-size: 13px;
}
.artist {
  font-size: 12px;
  color: var(--text-dim);
  margin-top: 2px;
}
.error {
  position: absolute;
  bottom: calc(100% + 8px);
  left: 20px;
  padding: 6px 12px;
  border-radius: 8px;
  background: #3a1d24;
  color: #f0a0b0;
  font-size: 12px;
  cursor: pointer;
}

.center {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.controls {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
}
.mode-btn {
  font-size: 15px;
}
.play-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  border-radius: 50%;
  background: var(--accent);
  color: #fff;
  font-size: 16px;
  transition: opacity 0.15s;
}
.play-btn:hover {
  opacity: 0.88;
}
.icon-btn.disabled {
  opacity: 0.35;
  pointer-events: none;
}
.quality {
  margin-left: 8px;
  height: 26px;
  padding: 0 6px;
  border-radius: 6px;
  border: 1px solid var(--border);
  background: var(--panel-2);
  font-size: 12px;
  outline: none;
}

.progress-row {
  display: flex;
  align-items: center;
  gap: 10px;
}
.time {
  font-size: 11px;
  color: var(--text-dim);
  width: 42px;
  text-align: center;
  flex-shrink: 0;
  font-variant-numeric: tabular-nums;
}
.progress {
  flex: 1;
}

.volume {
  display: flex;
  align-items: center;
  gap: 8px;
  justify-content: flex-end;
}
.vol-icon {
  font-size: 14px;
}
.vol-slider {
  width: 100px;
}
</style>
