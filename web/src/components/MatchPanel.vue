<script setup>
// 侧栏「匹配列表」面板:常驻轮询任务进度 + 控制按钮 + 共享 MatchList。
// 导入入口复用顶栏弹窗(emit import);入列成功后通知父级刷新播放列表。
import { computed, onMounted, onUnmounted, ref } from "vue";
import { getMatchJob, matchPause, matchReset, matchStart, placeholderAdd } from "../api";
import MatchList from "./MatchList.vue";

const emit = defineEmits(["applied", "import"]);

const summary = ref(null);
const job = ref(null);
const busy = ref(false);
const confirmReset = ref(false);
let resetTimer = null;
let pollTimer = null;

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
  } catch {
    /* 静默,下轮重试 */
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
// 各操作(开始/暂停/导入/选择/入列)后另有即时 pollOnce
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

const statusText = computed(() => {
  if (!summary.value) return "";
  const s = summary.value;
  switch (s.status) {
    case "idle":
      return "待开始";
    case "searching":
      return s.current
        ? `搜索中:${s.current.name}(${s.total - s.pending}/${s.total})`
        : "搜索中…";
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

async function doStart() {
  busy.value = true;
  try {
    await matchStart();
    await pollOnce();
  } catch {
    /* 静默 */
  } finally {
    busy.value = false;
  }
}

async function doPause() {
  busy.value = true;
  try {
    await matchPause();
    await pollOnce();
  } catch {
    /* 静默 */
  } finally {
    busy.value = false;
  }
}

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
  } catch {
    /* 静默 */
  } finally {
    busy.value = false;
  }
}

// ---------------------------------------------------------------- 占位入列

const notice = ref("");

async function doPlaceholderAdd() {
  busy.value = true;
  notice.value = "";
  try {
    const r = await placeholderAdd();
    notice.value = `已加入 ${r.added} 首占位(播放时即时匹配)`;
    if (r.added > 0) emit("applied");
  } catch (e) {
    notice.value = e.message || "加入失败";
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <div class="match-panel">
    <!-- 空态:未建任务 -->
    <div v-if="!summary" class="empty">
      <div class="empty-text">暂无匹配任务</div>
      <button class="primary" @click="emit('import')">导入歌单</button>
    </div>

    <template v-else>
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
            · 已入列 {{ summary.applied }} 首
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
            {{ confirmReset ? "确认重置?" : "重置" }}
          </button>
          <button class="ghost" :disabled="busy" @click="doPlaceholderAdd">
            全部加入播放列表(占位)
          </button>
        </div>
        <div v-if="notice" class="notice">{{ notice }}</div>
      </div>

      <MatchList :job="job" @applied="emit('applied')" />
    </template>
  </div>
</template>

<style scoped>
.match-panel {
  display: flex;
  flex-direction: column;
  flex: 1;
  padding: 14px 16px;
  gap: 10px;
  min-height: 0;
}
.empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
}
.empty-text {
  color: var(--text-dim);
  font-size: 13px;
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
  padding: 6px 14px;
  border-radius: 14px;
  border: 1px solid var(--border);
  color: var(--text-dim);
  font-size: 12px;
}
.danger-ghost {
  padding: 6px 12px;
  border-radius: 14px;
  border: 1px solid #e56d6d;
  color: #e56d6d;
  font-size: 12px;
}
.danger-ghost.armed {
  background: #e56d6d;
  color: #fff;
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
  flex-wrap: wrap;
}
.notice {
  font-size: 12px;
  color: #6fd08c;
}
</style>
