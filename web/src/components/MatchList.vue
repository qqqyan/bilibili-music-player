<script setup>
// 匹配歌曲列表(共享组件):筛选、展开选候选、批量勾选入列。
// 由 MatchDialog 与 MatchPanel 共用;job 为完整任务对象(在父组件维护轮询)。
import { computed, ref } from "vue";
import { formatTime, matchApply, matchChoose } from "../api";

const props = defineProps({
  job: { type: Object, default: null },
});
const emit = defineEmits(["applied"]);

const filter = ref("all");
const selected = ref(new Set()); // 勾选的 netease_id
const expanded = ref(null);
const error = ref("");
const notice = ref("");
const busy = ref(false);

const FILTERS = [
  { id: "all", label: "全部" },
  { id: "matched", label: "已匹配" },
  { id: "review", label: "待选择" },
  { id: "no_match", label: "未匹配" },
];

const counts = computed(() => {
  const songs = props.job?.songs || [];
  return {
    all: songs.length,
    matched: songs.filter((s) => s.status === "matched").length,
    review: songs.filter((s) => s.status === "review").length,
    no_match: songs.filter((s) => s.status === "no_match").length,
  };
});

const filteredSongs = computed(() => {
  if (!props.job?.songs) return [];
  if (filter.value === "all") return props.job.songs;
  return props.job.songs.filter((x) => x.status === filter.value);
});

function isSelectable(song) {
  return song.status === "matched" && !!song.chosen && !song.applied;
}

const selectableCount = computed(() =>
  filteredSongs.value.filter(isSelectable).length
);

async function onChoose(song, bvid) {
  error.value = "";
  try {
    const updated = await matchChoose(song.netease_id, bvid);
    const list = props.job?.songs;
    const idx = list?.findIndex((s) => s.netease_id === song.netease_id);
    if (idx >= 0) list[idx] = updated;
    if (updated.status !== "matched") selected.value.delete(song.netease_id);
  } catch (e) {
    error.value = e.message || "选择失败";
  }
}

function toggleSelect(song) {
  if (!isSelectable(song)) return;
  const id = song.netease_id;
  const next = new Set(selected.value);
  if (next.has(id)) next.delete(id);
  else next.add(id);
  selected.value = next;
}

function toggleSelectAll() {
  const all = filteredSongs.value.filter(isSelectable).map((s) => s.netease_id);
  const allSelected = all.length && all.every((id) => selected.value.has(id));
  selected.value = allSelected ? new Set() : new Set(all);
}

async function doApply() {
  if (!selected.value.size) return;
  busy.value = true;
  error.value = "";
  try {
    const r = await matchApply([...selected.value]);
    notice.value = `新增 ${r.added} 首 / 重复跳过 ${r.skipped_duplicates} 首`;
    if (r.added > 0) emit("applied");
    selected.value = new Set();
  } catch (e) {
    error.value = e.message || "添加失败";
  } finally {
    busy.value = false;
  }
}

function statusIcon(song) {
  if (song.status === "matched") return "✓";
  if (song.status === "review") return "?";
  if (song.status === "no_match") return "✕";
  return "◷";
}

// ---------------------------------------------------------------- 悬浮详情
// 候选/歌曲信息完整展示:全名、UP、时长/播放/得分、打分原因、视频简介。
// fixed 定位 + 延时隐藏(可移入浮层),规避列表 overflow 裁剪。
const hoverDetail = ref(null); // { cand, x, y }
let detailTimer = null;

function onDetailEnter(cand, e) {
  clearTimeout(detailTimer);
  const rect = e.currentTarget.getBoundingClientRect();
  hoverDetail.value = {
    cand,
    x: Math.max(8, rect.left - 312),
    y: Math.min(rect.top, window.innerHeight - 340),
  };
}

function onDetailLeave() {
  clearTimeout(detailTimer);
  detailTimer = setTimeout(() => (hoverDetail.value = null), 200);
}
</script>

<template>
  <div class="match-list">
    <div class="filters">
      <button
        v-for="f in FILTERS"
        :key="f.id"
        :class="{ on: filter === f.id }"
        @click="filter = f.id"
      >
        {{ f.label }} {{ counts[f.id] }}
      </button>
    </div>

    <div class="song-list">
      <div v-if="!filteredSongs.length" class="empty">没有歌曲</div>
      <div
        v-for="song in filteredSongs"
        :key="song.netease_id"
        class="song"
        :class="{ expanded: expanded === song.netease_id }"
        @click="expanded = expanded === song.netease_id ? null : song.netease_id"
      >
        <div class="song-main">
          <input
            type="checkbox"
            :checked="selected.has(song.netease_id)"
            :disabled="!isSelectable(song)"
            @click.stop="toggleSelect(song)"
          />
          <span
            class="status-icon"
            :class="song.status"
            :title="song.status === 'matched' ? '已匹配' : song.status === 'review' ? '待选择' : song.status === 'no_match' ? '未匹配' : '处理中'"
          >
            {{ statusIcon(song) }}
          </span>
          <div class="song-meta">
            <div class="song-name">{{ song.name }}</div>
            <div class="song-artists">{{ song.artists.join(" / ") }}</div>
          </div>
          <div class="chosen">
            <template v-if="song.chosen">
              <div
                class="chosen-title ellipsis detail-anchor"
                @mouseenter="onDetailEnter(song.chosen, $event)"
                @mouseleave="onDetailLeave"
              >
                {{ song.chosen.title }}
              </div>
              <div class="chosen-sub">
                UP:{{ song.chosen.up }} · score {{ song.chosen.score }}
              </div>
            </template>
            <div v-else class="chosen-empty">
              {{ song.status === "review" ? "待选择" : song.status === "no_match" ? "无匹配" : "…" }}
            </div>
          </div>
          <span v-if="song.applied" class="applied-badge">已加</span>
        </div>

        <div v-if="expanded === song.netease_id" class="song-detail" @click.stop>
          <div class="cand-group-title">选择匹配候选:</div>
          <label
            v-for="c in song.candidates"
            :key="c.bvid"
            class="cand"
            :class="{ on: song.status === 'matched' && song.chosen?.bvid === c.bvid }"
            @mouseenter="onDetailEnter(c, $event)"
            @mouseleave="onDetailLeave"
          >
            <input
              type="radio"
              :name="'cand-' + song.netease_id"
              :checked="song.status === 'matched' && song.chosen?.bvid === c.bvid"
              @change="onChoose(song, c.bvid)"
            />
            <span class="cand-title ellipsis">{{ c.title }}</span>
            <span class="cand-meta">
              {{ c.up }} · {{ formatTime(c.duration_s) }} · {{ (c.play || 0).toLocaleString() }} 播放 ·
              score {{ c.score }}
            </span>
            <span v-if="c.reason" class="cand-reason ellipsis" :title="c.reason">
              {{ c.reason }}
            </span>
          </label>
          <label class="cand" :class="{ on: song.status === 'no_match' }">
            <input
              type="radio"
              :name="'cand-' + song.netease_id"
              :checked="song.status === 'no_match'"
              @change="onChoose(song, null)"
            />
            <span class="cand-title">无匹配(标记后不参与批量添加)</span>
          </label>
        </div>
      </div>
    </div>

    <div class="batch-bar">
      <label class="select-all">
        <input
          type="checkbox"
          :checked="selectableCount > 0 && selected.size === selectableCount"
          :disabled="!selectableCount"
          @change="toggleSelectAll"
        />
        全选(当前筛选)
      </label>
      <span class="selected-count">已选 {{ selected.size }} 首</span>
      <button
        class="primary"
        :disabled="busy || !selected.size"
        @click="doApply"
      >
        添加选中到播放列表
      </button>
      <span v-if="notice" class="notice">{{ notice }}</span>
    </div>

    <div v-if="error" class="error">{{ error }}</div>

    <!-- 悬浮详情(候选/已选曲目完整信息) -->
    <div
      v-if="hoverDetail"
      class="hover-detail"
      :style="{ left: hoverDetail.x + 'px', top: hoverDetail.y + 'px' }"
      @mouseenter="clearTimeout(detailTimer)"
      @mouseleave="onDetailLeave"
    >
      <div class="hd-title">{{ hoverDetail.cand.title }}</div>
      <div class="hd-row">
        <span class="hd-label">UP:</span> {{ hoverDetail.cand.up }}
        <span class="hd-bvid">{{ hoverDetail.cand.bvid }}</span>
      </div>
      <div class="hd-row">
        <span class="hd-label">时长:</span> {{ formatTime(hoverDetail.cand.duration_s) }}
        · <span class="hd-label">播放:</span> {{ (hoverDetail.cand.play || 0).toLocaleString() }}
        · <span class="hd-label">得分:</span> {{ hoverDetail.cand.score }}
      </div>
      <div v-if="hoverDetail.cand.reason" class="hd-row">
        <span class="hd-label">打分:</span> {{ hoverDetail.cand.reason }}
      </div>
      <div v-if="hoverDetail.cand.description" class="hd-row hd-desc">
        <span class="hd-label">简介:</span> {{ hoverDetail.cand.description }}
      </div>
    </div>
  </div>
</template>

<style scoped>
.match-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-height: 0;
  flex: 1;
}
.filters {
  display: flex;
  gap: 4px;
  border-bottom: 1px solid var(--border);
  padding-bottom: 4px;
  flex-shrink: 0;
}
.filters button {
  padding: 6px 12px;
  font-size: 12px;
  color: var(--text-dim);
  border-bottom: 2px solid transparent;
}
.filters button.on {
  color: var(--accent);
  border-bottom-color: var(--accent);
}

.song-list {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-height: 0;
}
.empty {
  padding: 24px;
  text-align: center;
  color: var(--text-dim);
  font-size: 13px;
}
.song {
  border: 1px solid transparent;
  border-radius: 8px;
}
.song.expanded {
  border-color: var(--border);
}
.song-main {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 6px 8px;
  border-radius: 8px;
  cursor: pointer;
}
.song-main:hover {
  background: var(--hover);
}
.status-icon {
  width: 18px;
  text-align: center;
  font-size: 13px;
  flex-shrink: 0;
}
.status-icon.matched {
  color: #6fd08c;
}
.status-icon.review {
  color: #e5a96d;
}
.status-icon.no_match {
  color: var(--text-dim);
}
.song-meta {
  width: 150px;
  min-width: 0;
  flex-shrink: 0;
}
.song-name {
  font-size: 13px;
}
.song-artists {
  font-size: 11px;
  color: var(--text-dim);
  margin-top: 2px;
}
.chosen {
  flex: 1;
  min-width: 0;
}
.chosen-title {
  font-size: 12px;
}
.chosen-sub {
  font-size: 11px;
  color: var(--text-dim);
  margin-top: 2px;
}
.chosen-empty {
  font-size: 12px;
  color: var(--text-dim);
}
.applied-badge {
  font-size: 10px;
  color: #6fd08c;
  border: 1px solid #6fd08c;
  border-radius: 8px;
  padding: 1px 6px;
  flex-shrink: 0;
}

.song-detail {
  padding: 6px 8px 10px 36px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.cand-group-title {
  font-size: 11px;
  color: var(--text-dim);
}
.cand {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 12px;
}
.cand:hover {
  background: var(--hover);
}
.cand.on {
  background: var(--accent-soft);
}
.cand-title {
  max-width: 260px;
  flex-shrink: 0;
}
.cand-meta {
  color: var(--text-dim);
  font-size: 11px;
  flex-shrink: 0;
}
.cand-reason {
  color: var(--text-dim);
  font-size: 11px;
  margin-left: auto;
  max-width: 160px;
}

.batch-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  border-top: 1px solid var(--border);
  padding-top: 10px;
  flex-shrink: 0;
  flex-wrap: wrap;
}
.select-all {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--text-dim);
}
.selected-count {
  font-size: 12px;
  color: var(--text-dim);
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
.notice {
  font-size: 12px;
  color: #6fd08c;
}
.error {
  color: #e56d6d;
  font-size: 12px;
}

.ellipsis {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 悬浮详情 */
.hover-detail {
  position: fixed;
  z-index: 80;
  width: 300px;
  padding: 12px 14px;
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 10px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.45);
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 12px;
  line-height: 1.6;
}
.hd-title {
  font-size: 13px;
  font-weight: 600;
  white-space: normal;
  word-break: break-all;
}
.hd-row {
  color: var(--text-dim);
}
.hd-label {
  color: var(--text);
}
.hd-bvid {
  margin-left: 6px;
  font-size: 11px;
  color: var(--text-dim);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 0 6px;
}
.hd-desc {
  max-height: 96px;
  overflow-y: auto;
  white-space: normal;
}
</style>
