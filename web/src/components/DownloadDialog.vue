<script setup>
import { ref } from "vue";

const emit = defineEmits(["close", "confirm"]);

// 档位列表(id 与后端音质/画质枚举一致)
const AUDIO_OPTIONS = [
  { id: -1, label: "最高可用" },
  { id: 30216, label: "64K" },
  { id: 30232, label: "132K" },
  { id: 30280, label: "192K" },
  { id: 30251, label: "Hi-Res(需登录)" },
  { id: 30250, label: "杜比(需登录)" },
];
const VIDEO_OPTIONS = [
  { id: -1, label: "最高可用" },
  { id: 16, label: "360P" },
  { id: 32, label: "480P" },
  { id: 64, label: "720P" },
  { id: 80, label: "1080P" },
  { id: 116, label: "1080P60" },
  { id: 120, label: "4K" },
  { id: 127, label: "8K" },
];

const audio = ref(-1);
const video = ref(-1);
</script>

<template>
  <div class="mask" @click.self="emit('close')">
    <div class="dialog">
      <div class="head">
        <span class="title">下载全部</span>
        <button class="close-btn" @click="emit('close')">✕</button>
      </div>
      <p class="hint">
        遍历播放列表下载所选档位;某首没有该档时会自动降级到它最好的可用档。
      </p>
      <label>音质</label>
      <select v-model.number="audio">
        <option v-for="o in AUDIO_OPTIONS" :key="o.id" :value="o.id">
          {{ o.label }}
        </option>
      </select>
      <label>画质(视频画面)</label>
      <select v-model.number="video">
        <option v-for="o in VIDEO_OPTIONS" :key="o.id" :value="o.id">
          {{ o.label }}
        </option>
      </select>
      <button class="primary" @click="emit('confirm', { audio, video })">
        开始下载
      </button>
    </div>
  </div>
</template>

<style scoped>
.mask {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.55);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
}
.dialog {
  width: 320px;
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.title {
  font-size: 16px;
  font-weight: 600;
}
.close-btn {
  color: var(--text-dim);
  padding: 4px;
}
.hint {
  font-size: 12px;
  color: var(--text-dim);
  line-height: 1.7;
}
label {
  font-size: 12px;
  color: var(--text-dim);
}
select {
  height: 34px;
  padding: 0 10px;
  border-radius: 8px;
  border: 1px solid var(--border);
  background: var(--panel-2);
  outline: none;
}
.primary {
  margin-top: 8px;
  height: 36px;
  border-radius: 18px;
  background: var(--accent);
  color: #fff;
  font-weight: 600;
}
</style>
