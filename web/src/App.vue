<script setup>
import { onMounted, ref } from "vue";
import { usePlayerStore } from "./stores/player";
import { searchTracks } from "./api";
import SearchBar from "./components/SearchBar.vue";
import SearchResults from "./components/SearchResults.vue";
import Playlist from "./components/Playlist.vue";
import PlayerBar from "./components/PlayerBar.vue";

const store = usePlayerStore();
const audioEl = ref(null);
const videoEl = ref(null);

// 搜索状态
const results = ref([]);
const hasMore = ref(false);
const searching = ref(false);
const searchError = ref("");
const keyword = ref("");
const page = ref(1);

onMounted(async () => {
  store.attachMedia(audioEl.value, videoEl.value);
  await store.loadPlaylist();
  // 轮询下载队列状态(本地服务,开销可忽略)
  setInterval(() => store.refreshCacheStatus(), 5000);
});

async function doSearch(kw) {
  keyword.value = kw;
  page.value = 1;
  searching.value = true;
  searchError.value = "";
  try {
    const data = await searchTracks(kw, 1);
    results.value = data.items;
    hasMore.value = data.has_more;
  } catch (e) {
    results.value = [];
    searchError.value = e.message;
  } finally {
    searching.value = false;
  }
}

async function loadMore() {
  if (!hasMore.value || searching.value) return;
  searching.value = true;
  try {
    const data = await searchTracks(keyword.value, page.value + 1);
    results.value.push(...data.items);
    hasMore.value = data.has_more;
    page.value += 1;
  } catch (e) {
    searchError.value = e.message;
  } finally {
    searching.value = false;
  }
}
</script>

<template>
  <div class="layout">
    <header class="topbar">
      <div class="brand">
        <span class="brand-dot"></span>
        bilibili 音乐播放器
      </div>
      <SearchBar :loading="searching" @search="doSearch" />
    </header>

    <main class="main">
      <section class="left">
        <!-- MV 画面区(MV 模式开启且有画面流时显示) -->
        <!-- 注意:必须用 v-show 保持 video 元素常驻 DOM,否则首次开启前
             videoEl 为 null,store 无法操控元素 -->
        <Transition name="mv-fade">
          <div
            v-show="store.mvEnabled && store.currentVideoStream"
            class="mv-box"
          >
            <video ref="videoEl" class="mv-video" controls playsinline></video>
            <div v-if="store.mvEnabled && !store.mvReady" class="mv-loading">
              MV 缓冲中…
            </div>
          </div>
        </Transition>
        <SearchResults
          :items="results"
          :loading="searching"
          :has-more="hasMore"
          :error="searchError"
          @play="store.playFromSearch"
          @add="(t) => store.addTrack(t)"
          @load-more="loadMore"
        />
      </section>

      <aside class="right">
        <Playlist />
      </aside>
    </main>

    <footer class="bottombar">
      <PlayerBar />
    </footer>

    <!-- 音频输出统一由该元素驱动 -->
    <audio ref="audioEl" preload="auto"></audio>
  </div>
</template>

<style scoped>
.layout {
  height: 100%;
  display: grid;
  grid-template-rows: auto 1fr auto;
}

.topbar {
  display: flex;
  align-items: center;
  gap: 32px;
  padding: 12px 20px;
  background: var(--panel);
  border-bottom: 1px solid var(--border);
}

.brand {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 16px;
  font-weight: 600;
  white-space: nowrap;
}
.brand-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: var(--accent);
  box-shadow: 0 0 8px var(--accent);
}

.main {
  display: grid;
  grid-template-columns: 1fr 340px;
  gap: 16px;
  padding: 16px 20px;
  overflow: hidden;
  min-height: 0;
}

.left {
  overflow-y: auto;
  padding-right: 4px;
}

.mv-box {
  position: relative;
  margin-bottom: 16px;
  border-radius: 10px;
  overflow: hidden;
  background: #000;
  border: 1px solid var(--border);
}
.mv-video {
  display: block;
  width: 100%;
  max-height: 46vh;
  aspect-ratio: 16 / 9;
  object-fit: contain;
  background: #000;
}
.mv-loading {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  color: var(--text-dim);
}

.right {
  overflow-y: auto;
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 12px;
  min-height: 0;
}

.bottombar {
  border-top: 1px solid var(--border);
  background: var(--panel);
  padding: 10px 20px;
}

.mv-fade-enter-active,
.mv-fade-leave-active {
  transition: opacity 0.25s;
}
.mv-fade-enter-from,
.mv-fade-leave-to {
  opacity: 0;
}
</style>
