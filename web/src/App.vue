<script setup>
import { onMounted, ref } from "vue";
import { usePlayerStore } from "./stores/player";
import { authLogout, authStatus, getUserProfile, searchTracks, searchUsers } from "./api";
import SearchBar from "./components/SearchBar.vue";
import SearchResults from "./components/SearchResults.vue";
import Playlist from "./components/Playlist.vue";
import PlayerBar from "./components/PlayerBar.vue";
import SettingsDialog from "./components/SettingsDialog.vue";
import UserProfile from "./components/UserProfile.vue";

const store = usePlayerStore();
const audioEl = ref(null);
const videoEl = ref(null);

// 左栏滚动容器:新搜索回顶 + 「回到顶部」悬浮按钮
const leftEl = ref(null);
const showBackTop = ref(false);

function onLeftScroll() {
  showBackTop.value = (leftEl.value?.scrollTop ?? 0) > 400;
}

function scrollToTop() {
  leftEl.value?.scrollTo({ top: 0, behavior: "smooth" });
}

// 搜索状态
const results = ref([]);
const hasMore = ref(false);
const searching = ref(false);
const searchError = ref("");
const keyword = ref("");
const page = ref(1);
// UP 主:搜索结果区 + 主页视图
const users = ref([]);
const userView = ref(null); // { user, videos, hasMore, page, loading, error }

// 登录状态与设置面板
const auth = ref({ logged_in: false, user: null });
const showSettings = ref(false);
const settingsTab = ref("settings");

function openSettings(tab) {
  settingsTab.value = tab;
  showSettings.value = true;
}

async function fetchAuth() {
  try {
    auth.value = await authStatus();
  } catch {
    /* 后端不可达时忽略 */
  }
}

async function onLoginSuccess() {
  showSettings.value = false;
  await fetchAuth();
  // 登录后凭证已热更新:刷新当前曲目档位(其余曲目在播放时自动检查)
  await store.refreshResolvedStreams();
}

async function doLogout() {
  await authLogout().catch(() => {});
  await fetchAuth();
  await store.refreshResolvedStreams();
}

onMounted(async () => {
  store.attachMedia(audioEl.value, videoEl.value);
  await store.loadPlaylist();
  // 轮询下载队列状态(本地服务,开销可忽略;2s 让下载图标更实时)
  setInterval(() => store.refreshCacheStatus(), 2000);
  await fetchAuth();
  await store.loadSettings();
});

async function doSearch(kw) {
  keyword.value = kw;
  page.value = 1;
  searching.value = true;
  searchError.value = "";
  userView.value = null; // 新搜索退出 UP 主页
  leftEl.value?.scrollTo({ top: 0 }); // 新搜索回到列表顶部
  try {
    const [data, upList] = await Promise.all([
      searchTracks(kw, 1),
      searchUsers(kw, 1).catch(() => []),
    ]);
    results.value = data.items;
    hasMore.value = data.has_more;
    users.value = upList;
  } catch (e) {
    results.value = [];
    searchError.value = e.message;
  } finally {
    searching.value = false;
  }
}

/** 进入 UP 主主页 */
async function openUser(mid) {
  userView.value = { user: null, videos: [], hasMore: false, page: 1, loading: true, error: "" };
  leftEl.value?.scrollTo({ top: 0 }); // 从列表底部进入主页时回到顶部
  try {
    const data = await getUserProfile(mid, 1);
    userView.value.user = data.user;
    userView.value.videos = data.videos;
    userView.value.hasMore = data.has_more;
    userView.value.page = 1;
  } catch (e) {
    userView.value.error = e.message;
  } finally {
    userView.value.loading = false;
  }
}

function backToSearch() {
  userView.value = null;
}

/** UP 主页加载更多投稿 */
async function loadMoreUserVideos() {
  const view = userView.value;
  if (!view || view.loading || !view.hasMore) return;
  view.loading = true;
  try {
    const data = await getUserProfile(view.user.mid, view.page + 1);
    view.videos.push(...data.videos);
    view.hasMore = data.has_more;
    view.page += 1;
  } catch (e) {
    view.error = e.message;
  } finally {
    view.loading = false;
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

/** 回退主页:清空搜索结果与关键词,主区回到初始状态 */
function clearSearch() {
  results.value = [];
  keyword.value = "";
  hasMore.value = false;
  searchError.value = "";
  page.value = 1;
  users.value = [];
  userView.value = null;
}
</script>

<template>
  <div class="layout">
    <header class="topbar">
      <div class="brand">
        <span class="brand-dot"></span>
        bilibili 音乐播放器
      </div>
      <SearchBar
        :loading="searching"
        :has-results="results.length > 0 || !!keyword"
        @search="doSearch"
        @clear="clearSearch"
      />
      <span v-if="store.offline" class="offline-badge" title="后端服务不可达,自动重试中">
        ⚠ 后端离线,重试中…
      </span>
      <div class="auth-area">
        <template v-if="auth.logged_in">
          <img
            v-if="auth.user?.face"
            class="avatar"
            :src="auth.user.face"
            alt=""
            title="账号设置"
            @click="openSettings('account')"
          />
          <span class="nickname">{{ auth.user?.name || "已登录" }}</span>
        </template>
        <button v-else class="login-btn" @click="openSettings('account')">
          登录
        </button>
        <button
          class="icon-btn"
          title="设置"
          @click="openSettings('settings')"
        >
          ⚙
        </button>
      </div>
    </header>

    <main class="main">
      <section ref="leftEl" class="left" @scroll="onLeftScroll">
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
        <!-- UP 主主页视图(始终渲染组件,加载状态内部展示,避免卸载导致滚动跳顶) -->
        <UserProfile
          v-if="userView"
          :user="userView.user"
          :videos="userView.videos"
          :has-more="userView.hasMore"
          :loading="userView.loading"
          :error="userView.error"
          @back="backToSearch"
          @play="store.playFromSearch"
          @add="(t) => store.addTrack(t)"
          @load-more="loadMoreUserVideos"
          @open-user="openUser"
        />

        <!-- 搜索结果视图 -->
        <template v-else>
          <div v-if="users.length" class="users-bar">
            <div
              v-for="u in users"
              :key="u.mid"
              class="user-card"
              title="查看该 UP 主全部视频"
              @click="openUser(u.mid)"
            >
              <img class="u-face" :src="u.face" alt="" />
              <div class="u-meta">
                <div class="u-name ellipsis">{{ u.name }}</div>
                <div class="u-fans">粉丝 {{ (u.fans ?? 0).toLocaleString() }}</div>
              </div>
            </div>
          </div>
          <SearchResults
            :items="results"
            :loading="searching"
            :has-more="hasMore"
            :error="searchError"
            @play="store.playFromSearch"
            @add="(t) => store.addTrack(t)"
            @load-more="loadMore"
            @open-user="openUser"
          />
        </template>

        <!-- 「回到顶部」悬浮按钮:滚动一段距离后才显示 -->
        <button
          v-show="showBackTop"
          class="back-top"
          title="回到顶部"
          @click="scrollToTop"
        >
          ↑ 回到顶部
        </button>
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

    <SettingsDialog
      v-if="showSettings"
      :initial-tab="settingsTab"
      @close="showSettings = false"
      @login-success="onLoginSuccess"
    />
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

.offline-badge {
  margin-left: auto;
  font-size: 12px;
  color: #e5a96d;
  white-space: nowrap;
  animation: offline-pulse 2s ease-in-out infinite;
}
@keyframes offline-pulse {
  0%,
  100% {
    opacity: 1;
  }
  50% {
    opacity: 0.5;
  }
}
.auth-area {
  display: flex;
  align-items: center;
  gap: 8px;
  white-space: nowrap;
}
.avatar {
  width: 30px;
  height: 30px;
  border-radius: 50%;
  object-fit: cover;
  cursor: pointer;
}
.nickname {
  font-size: 13px;
  color: var(--text-dim);
}
.login-btn {
  height: 32px;
  padding: 0 18px;
  border-radius: 16px;
  border: 1px solid var(--accent);
  color: var(--accent);
  font-size: 13px;
  transition: all 0.15s;
}
.login-btn:hover {
  background: var(--accent-soft);
}
.logout-btn {
  font-size: 12px;
  color: var(--text-dim);
  padding: 4px 8px;
  border-radius: 6px;
}
.logout-btn:hover {
  color: #e56d6d;
  background: var(--hover);
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

.back-top {
  position: sticky;
  bottom: 16px;
  margin-left: auto;
  width: fit-content;
  padding: 8px 18px;
  border-radius: 18px;
  background: var(--panel);
  border: 1px solid var(--border);
  color: var(--text-dim);
  font-size: 13px;
  cursor: pointer;
  box-shadow: 0 4px 14px rgba(0, 0, 0, 0.3);
  transition: all 0.15s;
}
.back-top:hover {
  color: var(--accent);
  border-color: var(--accent);
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

/* UP 主卡片横条 */
.users-bar {
  display: flex;
  gap: 10px;
  overflow-x: auto;
  padding-bottom: 10px;
  margin-bottom: 6px;
}
.user-card {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  border-radius: 12px;
  background: var(--panel);
  border: 1px solid var(--border);
  cursor: pointer;
  flex-shrink: 0;
  transition: border-color 0.15s;
}
.user-card:hover {
  border-color: var(--accent);
}
.u-face {
  width: 42px;
  height: 42px;
  border-radius: 50%;
  object-fit: cover;
}
.u-meta {
  display: flex;
  flex-direction: column;
  gap: 2px;
  max-width: 140px;
}
.u-name {
  font-size: 13px;
}
.u-fans {
  font-size: 11px;
  color: var(--text-dim);
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
