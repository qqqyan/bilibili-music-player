<script setup>
import { computed, onMounted, ref } from "vue";
import {
  authStatus,
  getAudioList,
  getFavoriteFolders,
  getFavoriteItems,
} from "../api";
import { usePlayerStore } from "../stores/player";

const props = defineProps({
  initialTab: { type: String, default: "favorites" }, // favorites / audiolist
});
const emit = defineEmits(["close", "imported", "open-login"]);

const store = usePlayerStore();

const tab = ref(props.initialTab === "audiolist" ? "audiolist" : "favorites");
const authLoading = ref(true);
const loggedIn = ref(false);

const folders = ref([]);
const foldersLoading = ref(false);
const foldersError = ref("");

// 公开收藏夹预览
const favRef = ref("");
const favMedia = ref(null);
const favItems = ref([]);
const favHasMore = ref(false);

// 音频歌单
const amRef = ref("");
const audioInfo = ref(null);
const audioItems = ref([]);
const audioHasMore = ref(false);

const busy = ref(false);
const progressText = ref("");
const result = ref("");
const error = ref("");

const loggedInLabel = computed(() => (loggedIn.value ? "已登录" : "未登录"));

onMounted(async () => {
  try {
    const data = await authStatus();
    loggedIn.value = !!data.logged_in;
  } catch {
    loggedIn.value = false;
  } finally {
    authLoading.value = false;
  }
  if (loggedIn.value) await loadFolders();
});

/** B站收藏夹链接/ID → { mediaId } 或 { fid, mid } */
function parseFavoriteRef(text) {
  const s = (text || "").trim();
  if (!s) return null;
  let m = s.match(/medialist\/(?:detail|play)\/ml(\d+)/i);
  if (m) return { mediaId: Number(m[1]) };
  m = s.match(/[?&]media_id=(\d+)/i);
  if (m) return { mediaId: Number(m[1]) };
  m = s.match(/[?&]fid=(\d+)/i);
  if (m) {
    const uid = s.match(/space\.bilibili\.com\/(\d+)/i);
    return { fid: Number(m[1]), mid: uid ? Number(uid[1]) : null };
  }
  if (/^\d+$/.test(s)) return { mediaId: Number(s) };
  return null;
}

/** B站音频歌单链接/ID → am ID */
function parseAudioRef(text) {
  const s = (text || "").trim();
  const m =
    s.match(/(?:[?&]am_id=|(?:^|\/)am)(\d+)/i) || s.match(/^\d+$/);
  if (!m) return null;
  return Number(m[1] || m[0]);
}

async function loadFolders() {
  foldersLoading.value = true;
  foldersError.value = "";
  try {
    const data = await getFavoriteFolders();
    loggedIn.value = !!data.logged_in;
    folders.value = data.items || [];
  } catch (e) {
    foldersError.value = e.message;
  } finally {
    foldersLoading.value = false;
  }
}

async function resolveFavoriteMedia(parsed) {
  if (parsed.mediaId) return parsed.mediaId;
  if (!parsed.fid || !parsed.mid) {
    throw new Error("无法识别收藏夹链接,请粘贴带 fid 的收藏夹链接或收藏夹 ID");
  }
  const data = await getFavoriteFolders(parsed.mid);
  const folder = (data.items || []).find((f) => f.fid === parsed.fid);
  if (!folder) throw new Error("收藏夹不存在或不可见");
  return folder.media_id;
}

async function previewFavoriteRef() {
  error.value = "";
  result.value = "";
  const parsed = parseFavoriteRef(favRef.value);
  if (!parsed) {
    error.value = "无法识别收藏夹链接或 ID";
    return;
  }
  busy.value = true;
  progressText.value = "读取收藏夹…";
  try {
    const mediaId = await resolveFavoriteMedia(parsed);
    const data = await getFavoriteItems(mediaId, 1);
    favMedia.value = data.media;
    favItems.value = data.items || [];
    favHasMore.value = !!data.has_more;
  } catch (e) {
    error.value = e.message;
  } finally {
    busy.value = false;
    progressText.value = "";
  }
}

/** 导入整个收藏夹(自动翻页;重复条目跳过) */
async function importFavoriteMedia(mediaId) {
  error.value = "";
  result.value = "";
  busy.value = true;
  let page = 1;
  let total = 0;
  let added = 0;
  let dup = 0;
  try {
    while (page <= 200) {
      progressText.value = `正在导入收藏夹第 ${page} 页…`;
      const data = await getFavoriteItems(mediaId, page);
      const items = data.items || [];
      total += items.length;
      const n = store.addTracks(items);
      added += n;
      dup += items.length - n;
      if (!data.has_more) break;
      page += 1;
    }
    result.value = `已读取 ${total} 首,加入 ${added} 首${dup ? `,跳过重复/无效 ${dup} 首` : ""}`;
    emit("imported");
  } catch (e) {
    error.value = e.message;
  } finally {
    busy.value = false;
    progressText.value = "";
  }
}

async function importLoadedFavorites() {
  if (!favMedia.value) return;
  await importFavoriteMedia(favMedia.value.media_id);
}

async function loadAudioList() {
  error.value = "";
  result.value = "";
  const amId = parseAudioRef(amRef.value);
  if (!amId) {
    error.value = "无法识别歌单链接或 am ID";
    return;
  }
  busy.value = true;
  progressText.value = "读取 B站歌单…";
  try {
    const data = await getAudioList(amId, 1);
    audioInfo.value = data;
    audioItems.value = data.items || [];
    audioHasMore.value = !!data.has_more;
  } catch (e) {
    error.value = e.message;
  } finally {
    busy.value = false;
    progressText.value = "";
  }
}

async function importAudioList() {
  if (!audioInfo.value) return;
  const amId = audioInfo.value.am_id;
  error.value = "";
  result.value = "";
  busy.value = true;
  let page = 1;
  let total = 0;
  let added = 0;
  let dup = 0;
  try {
    while (page <= 200) {
      progressText.value = `正在导入歌单第 ${page} 页…`;
      const data = await getAudioList(amId, page);
      const items = data.items || [];
      total += items.length;
      const n = store.addTracks(items);
      added += n;
      dup += items.length - n;
      if (!data.has_more) break;
      page += 1;
    }
    result.value = `已读取 ${total} 首,加入 ${added} 首${dup ? `,跳过重复/无效 ${dup} 首` : ""}`;
    emit("imported");
  } catch (e) {
    error.value = e.message;
  } finally {
    busy.value = false;
    progressText.value = "";
  }
}

function onOpenLogin() {
  emit("open-login");
}

function switchTab(next) {
  if (busy.value) return;
  tab.value = next;
  error.value = "";
  result.value = "";
}
</script>

<template>
  <div class="mask" @click.self="emit('close')">
    <div class="dialog">
      <div class="head">
        <span class="title">导入 B站内容</span>
        <button class="close-btn" title="关闭" @click="emit('close')">✕</button>
      </div>

      <div class="tabs">
        <button :class="{ on: tab === 'favorites' }" @click="switchTab('favorites')">
          收藏夹
        </button>
        <button :class="{ on: tab === 'audiolist' }" @click="switchTab('audiolist')">
          音频歌单
        </button>
        <span class="login-state">{{ loggedInLabel }}</span>
      </div>

      <div class="body">
        <!-- 收藏夹 -->
        <template v-if="tab === 'favorites'">
          <div v-if="authLoading" class="hint">正在检查登录状态…</div>
          <div v-else-if="!loggedIn" class="hint login-hint">
            登录后可一键导入自己的收藏夹;也可以直接粘贴公开收藏夹链接或 ID。
            <button class="link-btn" @click="onOpenLogin">去登录</button>
          </div>

          <section v-if="loggedIn" class="section">
            <div class="section-head">
              <span>我的收藏夹</span>
              <button class="mini-btn" :disabled="busy" @click="loadFolders">刷新</button>
            </div>
            <div v-if="foldersLoading" class="hint">加载中…</div>
            <div v-else-if="foldersError" class="hint error">{{ foldersError }}</div>
            <div v-else-if="!folders.length" class="hint">没有可导入的收藏夹</div>
            <div v-else class="rows">
              <button
                v-for="f in folders"
                :key="f.media_id"
                class="row"
                :disabled="busy"
                :title="`导入「${f.title}」全部 ${f.count} 首`"
                @click="importFavoriteMedia(f.media_id)"
              >
                <img v-if="f.cover" class="thumb" :src="f.cover" alt="" />
                <div v-else class="thumb fallback">♪</div>
                <span class="row-main">
                  <span class="row-title">{{ f.title }}</span>
                  <span class="row-sub">{{ f.count }} 首</span>
                </span>
                <span class="row-action">一键导入</span>
              </button>
            </div>
          </section>

          <section class="section">
            <div class="section-head"><span>公开收藏夹</span></div>
            <div class="inline">
              <input
                v-model="favRef"
                type="text"
                placeholder="收藏夹链接 / medialist/.../ml123 / media_id"
                @keyup.enter="previewFavoriteRef"
              />
              <button class="primary slim" :disabled="busy" @click="previewFavoriteRef">
                读取
              </button>
            </div>
            <div class="hint">
              支持 space.bilibili.com/UID/favlist?fid=123、medialist/detail/ml123 或数字 media_id。
            </div>
            <div v-if="favMedia" class="media-preview">
              <img v-if="favMedia.cover" class="thumb big" :src="favMedia.cover" alt="" />
              <div v-else class="thumb big fallback">♪</div>
              <div class="media-meta">
                <div class="row-title">{{ favMedia.title || "收藏夹" }}</div>
                <div class="row-sub">
                  {{ favMedia.upper }} · {{ favMedia.count }} 首
                </div>
              </div>
            </div>
            <div v-if="favItems.length" class="rows">
              <div v-for="t in favItems" :key="t.id" class="row static">
                <img class="thumb" :src="t.cover" alt="" />
                <span class="row-main">
                  <span class="row-title">{{ t.title }}</span>
                  <span class="row-sub">{{ t.artist }}</span>
                </span>
                <span class="row-sub">{{ t.source }}</span>
              </div>
            </div>
            <div v-if="favHasMore" class="hint">列表还有更多,导入时会自动翻页。</div>
            <button
              v-if="favMedia && favItems.length"
              class="primary"
              :disabled="busy"
              @click="importLoadedFavorites"
            >
              导入全部 {{ favMedia.count || favItems.length }} 首
            </button>
          </section>
        </template>

        <!-- 音频歌单 -->
        <template v-else>
          <section class="section">
            <div class="inline">
              <input
                v-model="amRef"
                type="text"
                placeholder="B站歌单链接 / am123 / 数字 ID"
                @keyup.enter="loadAudioList"
              />
              <button class="primary slim" :disabled="busy" @click="loadAudioList">
                读取
              </button>
            </div>
            <div class="hint">
              支持 www.bilibili.com/audio/am123、space.bilibili.com/UID/audio?am_id=123 或数字 am ID。
            </div>
          </section>

          <section v-if="audioInfo" class="section">
            <div class="media-preview">
              <img v-if="audioInfo.cover" class="thumb big" :src="audioInfo.cover" alt="" />
              <div v-else class="thumb big fallback">♪</div>
              <div class="media-meta">
                <div class="row-title">{{ audioInfo.title }}</div>
                <div class="row-sub">
                  {{ audioInfo.upper }} · {{ audioInfo.count || audioItems.length }} 首
                </div>
                <div v-if="audioInfo.intro" class="row-sub intro">
                  {{ audioInfo.intro }}
                </div>
              </div>
            </div>
            <div class="rows">
              <div v-for="t in audioItems" :key="t.id" class="row static">
                <img class="thumb" :src="t.cover" alt="" />
                <span class="row-main">
                  <span class="row-title">{{ t.title }}</span>
                  <span class="row-sub">{{ t.artist }}</span>
                </span>
                <span class="row-sub">{{ t.source }}</span>
              </div>
            </div>
            <div v-if="audioHasMore" class="hint">列表还有更多,导入时会自动翻页。</div>
            <button
              v-if="audioItems.length"
              class="primary"
              :disabled="busy"
              @click="importAudioList"
            >
              导入全部 {{ audioInfo.count || audioItems.length }} 首
            </button>
          </section>
        </template>

        <div v-if="progressText" class="hint progress">{{ progressText }}</div>
        <div v-if="error" class="hint error">{{ error }}</div>
        <div v-if="result" class="hint success">{{ result }}</div>
      </div>
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
  width: 720px;
  max-width: calc(100vw - 48px);
  max-height: calc(100vh - 80px);
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 14px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px 10px;
}
.title {
  font-size: 16px;
  font-weight: 600;
}
.close-btn {
  color: var(--text-dim);
  padding: 4px;
}
.tabs {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 0 20px;
  border-bottom: 1px solid var(--border);
}
.tabs button {
  padding: 8px 12px;
  font-size: 13px;
  color: var(--text-dim);
  border-bottom: 2px solid transparent;
}
.tabs button.on {
  color: var(--accent);
  border-bottom-color: var(--accent);
}
.login-state {
  margin-left: auto;
  font-size: 12px;
  color: var(--text-dim);
}
.body {
  padding: 16px 20px 20px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.section {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 13px;
  font-weight: 600;
}
.mini-btn {
  font-size: 12px;
  color: var(--accent);
  padding: 2px 6px;
}
.mini-btn:disabled {
  opacity: 0.5;
}
.hint {
  font-size: 12px;
  color: var(--text-dim);
  line-height: 1.7;
}
.hint.error {
  color: #e56d6d;
}
.hint.success {
  color: #6fcf97;
}
.hint.progress {
  color: var(--accent);
}
.login-hint {
  display: flex;
  align-items: center;
  gap: 8px;
}
.link-btn {
  color: var(--accent);
  font-size: 12px;
  text-decoration: underline;
}
.inline {
  display: flex;
  gap: 8px;
}
.inline input {
  flex: 1;
  min-width: 0;
  height: 34px;
  padding: 0 12px;
  border-radius: 8px;
  border: 1px solid var(--border);
  background: var(--panel-2);
  outline: none;
  font-size: 13px;
}
.inline input:focus {
  border-color: var(--accent);
}
.primary {
  height: 38px;
  border-radius: 19px;
  background: var(--accent);
  color: #fff;
  font-weight: 600;
}
.primary.slim {
  height: 34px;
  padding: 0 18px;
  border-radius: 8px;
}
.primary:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}
.rows {
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: 300px;
  overflow-y: auto;
}
.row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 6px 8px;
  border-radius: 8px;
  text-align: left;
  background: var(--panel-2);
}
button.row {
  transition: background 0.15s;
}
button.row:hover {
  background: var(--hover);
}
.row.static {
  background: transparent;
}
.thumb {
  width: 48px;
  height: 32px;
  border-radius: 5px;
  object-fit: cover;
  flex-shrink: 0;
  background: #000;
}
.thumb.big {
  width: 96px;
  height: 60px;
}
.thumb.fallback {
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-dim);
  font-size: 16px;
}
.row-main {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
  flex: 1;
}
.row-title {
  font-size: 13px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.row-sub {
  font-size: 11px;
  color: var(--text-dim);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.row-action {
  font-size: 12px;
  color: var(--accent);
  flex-shrink: 0;
}
.media-preview {
  display: flex;
  gap: 12px;
  align-items: center;
  padding: 8px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--panel-2);
}
.media-meta {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}
.intro {
  white-space: normal;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}
</style>
