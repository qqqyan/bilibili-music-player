<script setup>
import { ref } from "vue";

defineProps({
  loading: Boolean,
});
const emit = defineEmits(["search"]);

const keyword = ref("");

function submit() {
  if (keyword.value.trim()) emit("search", keyword.value.trim());
}
</script>

<template>
  <div class="search-bar">
    <input
      v-model="keyword"
      class="search-input"
      type="text"
      placeholder="搜索 bilibili 视频,直接当音乐听…"
      @keyup.enter="submit"
    />
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
  max-width: 640px;
}
.search-input {
  flex: 1;
  height: 38px;
  padding: 0 16px;
  border-radius: 19px;
  border: 1px solid var(--border);
  background: var(--panel-2);
  outline: none;
  transition: border-color 0.15s;
}
.search-input:focus {
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
