<script setup>
import { onMounted, ref } from "vue";
import { getQualities } from "../api";

const emit = defineEmits(["close", "confirm"]);

// 档位列表由后端提供(唯一事实来源);失败时用兜底列表
const audioOptions = ref([{ id: -1, label: "最高可用" }]);
const videoOptions = ref([{ id: -1, label: "最高可用" }]);
const loadError = ref("");

onMounted(async () => {
  try {
    const data = await getQualities();
    audioOptions.value = [
      { id: -1, label: "最高可用" },
      ...data.audio.map((q) => ({
        id: q.id,
        label: q.label + (q.id > 30280 ? "(需登录)" : ""),
      })),
    ];
    videoOptions.value = [
      { id: -1, label: "最高可用" },
      ...data.video.map((q) => ({
        id: q.id,
        label: q.label + (q.id > 80 ? "(需登录)" : ""),
      })),
    ];
  } catch {
    loadError.value = "档位列表加载失败,仅可选最高档";
  }
});

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
      <div v-if="loadError" class="hint error">{{ loadError }}</div>
      <label>音质</label>
      <select v-model.number="audio">
        <option v-for="o in audioOptions" :key="o.id" :value="o.id">
          {{ o.label }}
        </option>
      </select>
      <label>画质(视频画面)</label>
      <select v-model.number="video">
        <option v-for="o in videoOptions" :key="o.id" :value="o.id">
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
.hint.error {
  color: #e56d6d;
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
