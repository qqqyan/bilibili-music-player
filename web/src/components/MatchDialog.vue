<script setup>
// 歌单匹配弹窗:导入 + 搜索控制 + 进度;歌曲列表复用 MatchList(与侧栏面板一致)。
import { computed, onMounted, onUnmounted, ref } from "vue";
import { usePlayerStore } from "../stores/player";
import {
  getMatchJob,
  importMatch,
  matchPause,
  matchReset,
  matchStart,
  placeholderAdd,
} from "../api";
import MatchList from "./MatchList.vue";

const store = usePlayerStore();

const emit = defineEmits(["close", "applied"]);

const summary = ref(null); // 轻量轮询字典
const job = ref(null); // 全量任务(打开/进度变化时拉取)
const error = ref("");
const notice = ref("");
const busy = ref(false);

// 导入表单
const importText = ref("");
const importName = ref("");
const importFileName = ref("");

let pollTimer = null;

const statusText = computed(() => {
  if (!summary.value) return "";
  const s = summary.value;
  switch (s.status) {
    case "idle":
      return "待开始";
    case "searching":
      return s.current
        ? `正在搜索:${s.current.name}(${s.total - s.pending}/${s.total})`
        : "正在搜索…";
    case "paused":
      return s.error ? `已暂停:${s.error}` : "已暂停";
    case "done":
      return "已完成";
    default:
      return s.status;
  }
});

const progressPct = computed(() => {
  const s = summary.value;
  if (!s || !s.total) return 0;
  return Math.round(((s.total - s.pending) / s.total) * 100);
});

/** 404(暂无任务)返回 null,其余错误抛出 */
async function fetchJobSafe(summaryOnly) {
  try {
    return await getMatchJob(summaryOnly);
  } catch (e) {
    if (e.message === "暂无匹配任务") return null;
    throw e;
  }
}

async function refreshSummary() {
  try {
    const s = await fetchJobSafe(true);
    if (s === null) {
      summary.value = null;
      job.value = null;
    } else {
      summary.value = s;
    }
  } catch {
    /* 轮询瞬断:保持现状,下一轮再试 */
  }
}

async function refreshFull() {
  if (!summary.value) return;
  try {
    job.value = await getMatchJob();
  } catch (e) {
    error.value = e.message || "加载匹配任务失败";
  }
}

async function pollOnce() {
  const prevStatus = summary.value?.status;
  const prevCurrent = summary.value?.current?.netease_id;
  await refreshSummary();
  if (
    summary.value &&
    (summary.value.status !== prevStatus ||
      summary.value.current?.netease_id !== prevCurrent)
  ) {
    await refreshFull();
  }
}

// 自调度轮询:搜索进行中 5s(进度需实时),空闲状态 60s(低频兜底);
// 各操作(导入/开始/暂停/重置)后另有即时 pollOnce
let first = true;
async function schedulePoll() {
  clearTimeout(pollTimer);
  await pollOnce();
  if (first && summary.value) {
    await refreshFull();
    first = false;
  }
  pollTimer = setTimeout(
    schedulePoll,
    summary.value?.status === "searching" ? 5000 : 60000
  );
}

onMounted(schedulePoll);

onUnmounted(() => clearTimeout(pollTimer));

// ---------------------------------------------------------------- 导入

function onFilePicked(e) {
  const file = e.target.files?.[0];
  if (!file) return;
  importFileName.value = file.name;
  if (!importName.value) importName.value = file.name.replace(/\.(json|jsonl|txt)$/i, "");
  const reader = new FileReader();
  reader.onload = () => {
    importText.value = String(reader.result || "");
  };
  reader.readAsText(file);
}

async function doImport() {
  if (!importText.value.trim()) {
    error.value = "请先粘贴歌单内容或选择文件";
    return;
  }
  busy.value = true;
  error.value = "";
  try {
    await importMatch(importName.value || "歌单", importText.value);
    await pollOnce();
    await refreshFull();
    notice.value = `导入成功,共 ${summary.value?.total ?? 0} 首`;
    // 开启「导入后全部加入播放列表」:以占位曲目入列(播放时即时匹配)
    if (store.settings.match_auto_add) {
      const r = await placeholderAdd().catch((e) => {
        error.value = `占位入列失败: ${e.message}`;
        return null;
      });
      if (r?.added) {
        notice.value += `,已加入 ${r.added} 首占位`;
        emit("applied");
      }
    }
  } catch (e) {
    error.value = e.message || "导入失败";
  } finally {
    busy.value = false;
  }
}

// ---------------------------------------------------------------- 任务控制

async function doStart() {
  busy.value = true;
  error.value = "";
  try {
    await matchStart();
    await pollOnce();
  } catch (e) {
    error.value = e.message;
  } finally {
    busy.value = false;
  }
}

async function doPause() {
  busy.value = true;
  try {
    await matchPause();
    await pollOnce();
  } catch (e) {
    error.value = e.message;
  } finally {
    busy.value = false;
  }
}

// 重置二次确认(同播放列表「清空」)
const confirmReset = ref(false);
let resetTimer = null;
async function onResetClick() {
  if (!confirmReset.value) {
    confirmReset.value = true;
    resetTimer = setTimeout(() => (confirmReset.value = false), 4000);
    return;
  }
  clearTimeout(resetTimer);
  confirmReset.value = false;
  busy.value = true;
  try {
    await matchReset();
    summary.value = null;
    job.value = null;
    notice.value = "";
    importText.value = "";
  } catch (e) {
    error.value = e.message;
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <div class="mask" @click.self="emit('close')">
    <div class="dialog">
      <div class="head">
        <span class="title">歌单匹配</span>
        <span v-if="summary" class="platform-tag">
          {{ summary.source_platform }} → {{ summary.target_platform }}
        </span>
        <button class="close-btn" @click="emit('close')">✕</button>
      </div>

      <!-- 空态:导入 -->
      <div v-if="!summary" class="import-area">
        <div class="desc">
          导入来源平台歌单(网易云歌单 JSON,或本应用匹配结果 JSONL 作种子):
        </div>
        <input
          v-model="importName"
          class="import-input"
          type="text"
          placeholder="任务名称(可选)"
        />
        <label class="file-btn">
          选择文件
          <input type="file" accept=".json,.jsonl,.txt" hidden @change="onFilePicked" />
        </label>
        <span v-if="importFileName" class="file-name">{{ importFileName }}</span>
        <textarea
          v-model="importText"
          class="import-text"
          placeholder="或直接粘贴歌单 JSON 内容…"
        ></textarea>
        <label class="checkbox">
          <input
            type="checkbox"
            :checked="store.settings.match_auto_add"
            @change="store.saveSetting({ match_auto_add: $event.target.checked })"
          />
          导入后全部加入播放列表(占位,播放时即时匹配)
        </label>
        <div class="import-actions">
          <button class="primary" :disabled="busy" @click="doImport">导入</button>
        </div>
        <div v-if="error" class="error">{{ error }}</div>
      </div>

      <!-- 任务视图 -->
      <div v-else class="job-area">
        <div class="toolbar">
          <div class="progress-row">
            <div class="progress-track">
              <div class="progress-fill" :style="{ width: progressPct + '%' }"></div>
            </div>
            <span class="progress-text">{{ progressPct }}%</span>
          </div>
          <div class="status-line">
            {{ statusText }}
            <span v-if="summary.applied" class="applied-count">
              (已加入播放列表 {{ summary.applied }} 首)
            </span>
          </div>
          <div class="controls">
            <button
              v-if="summary.status !== 'searching'"
              class="primary"
              :disabled="busy || (summary.status === 'done' && !summary.pending)"
              @click="doStart"
            >
              {{ summary.status === "paused" ? "继续" : "开始搜索" }}
            </button>
            <button v-else class="ghost" :disabled="busy" @click="doPause">暂停</button>
            <button
              v-if="summary.status !== 'searching'"
              class="danger-ghost"
              :class="{ armed: confirmReset }"
              @click="onResetClick"
            >
              {{ confirmReset ? "确认重置?" : "重置任务" }}
            </button>
          </div>
        </div>

        <MatchList :job="job" @applied="emit('applied')" />

        <div v-if="notice" class="notice">{{ notice }}</div>
        <div v-if="error" class="error">{{ error }}</div>
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
  width: 760px;
  height: 85vh;
  display: flex;
  flex-direction: column;
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 20px;
}
.head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
}
.title {
  font-size: 16px;
  font-weight: 600;
}
.platform-tag {
  font-size: 11px;
  color: var(--text-dim);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 2px 8px;
}
.close-btn {
  margin-left: auto;
  color: var(--text-dim);
  padding: 4px;
}
.desc {
  font-size: 12px;
  color: var(--text-dim);
  line-height: 1.6;
}
.error {
  color: #e56d6d;
  font-size: 12px;
  margin-top: 8px;
}
.notice {
  font-size: 12px;
  color: #6fd08c;
}

/* 导入区 */
.import-area {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 10px;
  overflow-y: auto;
}
.import-input {
  height: 30px;
  padding: 0 10px;
  border-radius: 6px;
  border: 1px solid var(--border);
  background: var(--panel-2);
  color: var(--text);
  outline: none;
  font-size: 13px;
}
.file-btn {
  align-self: flex-start;
  padding: 6px 14px;
  border-radius: 14px;
  border: 1px solid var(--accent);
  color: var(--accent);
  font-size: 12px;
  cursor: pointer;
}
.file-name {
  font-size: 12px;
  color: var(--text-dim);
}
.import-text {
  flex: 1;
  min-height: 200px;
  padding: 10px;
  border-radius: 8px;
  border: 1px solid var(--border);
  background: var(--panel-2);
  color: var(--text);
  outline: none;
  font-size: 12px;
  font-family: monospace;
  resize: vertical;
}
.import-actions {
  display: flex;
  justify-content: flex-end;
}
.checkbox {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--text-dim);
}

/* 任务视图 */
.job-area {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-height: 0;
}
.toolbar {
  display: flex;
  flex-direction: column;
  gap: 6px;
  flex-shrink: 0;
}
.progress-row {
  display: flex;
  align-items: center;
  gap: 10px;
}
.progress-track {
  flex: 1;
  height: 6px;
  border-radius: 3px;
  background: var(--panel-2);
  overflow: hidden;
}
.progress-fill {
  height: 100%;
  background: var(--accent);
  transition: width 0.4s;
}
.progress-text {
  font-size: 11px;
  color: var(--text-dim);
  width: 36px;
  text-align: right;
  font-variant-numeric: tabular-nums;
}
.status-line {
  font-size: 12px;
  color: var(--text-dim);
}
.applied-count {
  color: #6fd08c;
}
.controls {
  display: flex;
  gap: 8px;
}
.primary {
  padding: 6px 16px;
  border-radius: 14px;
  background: var(--accent);
  color: #fff;
  font-size: 12px;
}
.primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.ghost {
  padding: 6px 16px;
  border-radius: 14px;
  border: 1px solid var(--border);
  color: var(--text-dim);
  font-size: 12px;
}
.danger-ghost {
  padding: 6px 14px;
  border-radius: 14px;
  border: 1px solid #e56d6d;
  color: #e56d6d;
  font-size: 12px;
}
.danger-ghost.armed {
  background: #e56d6d;
  color: #fff;
}
</style>
