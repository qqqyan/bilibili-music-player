<script setup>
import { ref } from "vue";

defineProps({
  loading: Boolean,
  hasResults: Boolean,
});
const emit = defineEmits(["search", "clear"]);

const keyword = ref("");

function submit() {
  if (keyword.value.trim()) emit("search", keyword.value.trim());
}

function clearInput() {
  keyword.value = "";
  emit("clear");
}

function backHome() {
  keyword.value = "";
  emit("clear");
}
</script>

<template>
  <div class="search-bar">
    <button
      v-if="hasResults"
      class="back-btn"
      title="返回主页"
      @click="backHome"
    >
      ← 返回主页
    </button>
    <div class="input-wrap">
      <input
        v-model="keyword"
        class="search-input"
        type="text"
        placeholder="搜索 bilibili 视频,直接当音乐听…"
        @keyup.enter="submit"
      />
      <button
        v-if="keyword"
        class="clear-input-btn"
        title="清空输入"
        @click="clearInput"
      >
        ✕
      </button>
    </div>
    <button class="search-btn" :disabled="loading" @click="submit">
      {{ loading ? "搜索中…" : "搜索" }}
    </button>
  </div>
</template>

<style scoped>
.search-bar {
  display: flex;
  gap: 8px;
  flex: 1;
  max-width: 700px;
  align-items: center;
}
.input-wrap {
  position: relative;
  flex: 1;
  display: flex;
  align-items: center;
}
.search-input {
  flex: 1;
  height: 38px;
  padding: 0 34px 0 16px;
  border-radius: 19px;
  border: 1px solid var(--border);
  background: var(--panel-2);
  outline: none;
  transition: border-color 0.15s;
}
.search-input:focus {
  border-color: var(--accent);
}
.clear-input-btn {
  position: absolute;
  right: 10px;
  color: var(--text-dim);
  font-size: 12px;
  padding: 4px;
}
.clear-input-btn:hover {
  color: var(--text);
}
.back-btn {
  height: 32px;
  padding: 0 14px;
  border-radius: 16px;
  border: 1px solid var(--border);
  color: var(--text-dim);
  font-size: 13px;
  white-space: nowrap;
  transition: all 0.15s;
}
.back-btn:hover {
  color: var(--accent);
  border-color: var(--accent);
}
.search-btn {
  height: 38px;
  padding: 0 20px;
  border-radius: 19px;
  background: var(--accent);
  color: #fff;
  font-weight: 600;
  transition: opacity 0.15s;
}
.search-btn:hover {
  opacity: 0.88;
}
.search-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>
