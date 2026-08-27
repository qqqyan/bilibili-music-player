<script setup>
import { usePlayerStore } from "../stores/player";
import SearchResults from "./SearchResults.vue";

defineProps({
  user: { type: Object, required: true },
  videos: { type: Array, default: () => [] },
  hasMore: Boolean,
  loading: Boolean,
  error: String,
});
const emit = defineEmits(["back", "play", "add", "loadMore", "open-user"]);

const store = usePlayerStore();
</script>

<template>
  <div class="user-profile">
    <button class="back-btn" @click="emit('back')">← 返回搜索</button>

    <template v-if="user">
      <div class="header">
        <img class="face" :src="user.face" alt="" />
        <div class="info">
          <div class="name">{{ user.name }}</div>
          <div class="sign ellipsis" :title="user.sign">
            {{ user.sign || "这个人很懒,什么都没写" }}
          </div>
          <div class="stats">
            粉丝 {{ (user.fans ?? 0).toLocaleString() }}
            <template v-if="videos.length"> · 投稿 {{ videos.length }}+</template>
          </div>
        </div>
      </div>

      <div class="videos-title">全部视频</div>

      <SearchResults
        :items="videos"
        :loading="loading"
        :has-more="hasMore"
        :error="error"
        @play="emit('play', $event)"
        @add="emit('add', $event)"
        @load-more="emit('loadMore')"
        @open-user="emit('open-user', $event)"
      />
    </template>
    <div v-else-if="error" class="view-hint error">
      {{ error }}
      <button class="text-btn" @click="emit('back')">返回搜索</button>
    </div>
    <div v-else class="view-hint">加载中…</div>
  </div>
</template>

<style scoped>
.user-profile {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.back-btn {
  align-self: flex-start;
  padding: 6px 14px;
  border-radius: 14px;
  border: 1px solid var(--border);
  color: var(--text-dim);
  font-size: 13px;
}
.back-btn:hover {
  color: var(--accent);
  border-color: var(--accent);
}
.header {
  display: flex;
  gap: 14px;
  align-items: center;
  padding: 14px;
  border-radius: 12px;
  background: var(--panel);
  border: 1px solid var(--border);
}
.face {
  width: 72px;
  height: 72px;
  border-radius: 50%;
  object-fit: cover;
}
.info {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.name {
  font-size: 18px;
  font-weight: 600;
}
.sign {
  font-size: 12px;
  color: var(--text-dim);
  max-width: 420px;
}
.stats {
  font-size: 12px;
  color: var(--text-dim);
}
.videos-title {
  font-size: 14px;
  font-weight: 600;
  padding-left: 4px;
}
.view-hint {
  padding: 48px 16px;
  text-align: center;
  color: var(--text-dim);
}
.view-hint.error {
  color: #e56d6d;
}
.text-btn {
  margin-top: 10px;
  padding: 6px 16px;
  border-radius: 14px;
  border: 1px solid var(--border);
  color: var(--text-dim);
  font-size: 13px;
}
.text-btn:hover {
  color: var(--accent);
  border-color: var(--accent);
}
</style>
