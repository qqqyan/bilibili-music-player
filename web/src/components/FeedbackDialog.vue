<script setup>
// 应用内反馈:描述 + 截图 + 最近脱敏日志 → 预填 GitHub issue,并保存本地诊断包。
import { computed, onMounted, onUnmounted, ref } from "vue";
import { usePlayerStore } from "../stores/player";
import {
  authStatus,
  feedbackInfo,
  feedbackLogs,
  neteaseStatus,
  submitFeedback,
} from "../api";
import { clientContext } from "../diagnostics";

const props = defineProps({
  loggedIn: { type: Boolean, default: false },
});
const emit = defineEmits(["close"]);
const store = usePlayerStore();

const MAX_SHOT_EDGE = 2560;
const MAX_SHOT_BYTES = 15 * 1024 * 1024;

const title = ref("");
const description = ref("");
const includeLogs = ref(true);
const screenshot = ref(null); // { blob, url, name }
const screenshotCopied = ref(false);
const meta = ref({ repo: "qqqyan/bilibili-music-player", version: "" });
const logLines = ref([]);
const logTotal = ref(0);
const showLogs = ref(false);
const dropActive = ref(false);
const busy = ref(false);
const error = ref("");
const notice = ref("");
const fallbackUrl = ref("");
const fileInput = ref(null);
const loggedIn = ref(props.loggedIn);
const neteaseLoggedIn = ref(null);

let objectUrl = null;
let alive = true;

const canSubmit = computed(() => description.value.trim().length > 0 && !busy.value);

// ---------------------------------------------------------------- 截图

function revokeShot() {
  if (objectUrl) {
    URL.revokeObjectURL(objectUrl);
    objectUrl = null;
  }
}

function setShot(blob, name) {
  revokeShot();
  objectUrl = URL.createObjectURL(blob);
  screenshot.value = { blob, url: objectUrl, name };
  error.value = "";
  // 捕获/选择后立刻放进剪贴板:提交后用户可直接在 issue 里粘贴
  copyShot();
}

async function decodeImage(file) {
  if (typeof createImageBitmap === "function") {
    try {
      return await createImageBitmap(file);
    } catch {
      /* 某些 Safari 版本不支持,退回 <img> 解码 */
    }
  }
  const url = URL.createObjectURL(file);
  try {
    const img = new Image();
    img.src = url;
    await img.decode();
    return img;
  } finally {
    URL.revokeObjectURL(url);
  }
}

async function toPngBlob(file) {
  const bitmap = await decodeImage(file);
  const scale = Math.min(
    1,
    MAX_SHOT_EDGE / Math.max(bitmap.width, bitmap.height)
  );
  const canvas = document.createElement("canvas");
  canvas.width = Math.max(1, Math.round(bitmap.width * scale));
  canvas.height = Math.max(1, Math.round(bitmap.height * scale));
  canvas.getContext("2d").drawImage(bitmap, 0, 0, canvas.width, canvas.height);
  if (bitmap.close) bitmap.close();
  return await new Promise((resolve, reject) => {
    canvas.toBlob(
      (blob) => (blob ? resolve(blob) : reject(new Error("生成截图失败"))),
      "image/png"
    );
  });
}

async function importImage(file) {
  if (!file?.type?.startsWith("image/")) {
    error.value = "请选择图片文件";
    return;
  }
  if (file.size > MAX_SHOT_BYTES) {
    error.value = "截图过大(上限 15MB)";
    return;
  }
  try {
    setShot(await toPngBlob(file), file.name || "screenshot.png");
  } catch (e) {
    error.value = e.message || "处理截图失败";
  }
}

async function copyShot() {
  const shot = screenshot.value;
  if (!shot) return false;
  try {
    if (!navigator.clipboard?.write || typeof ClipboardItem === "undefined") {
      throw new Error("unsupported");
    }
    await navigator.clipboard.write([
      new ClipboardItem({ "image/png": shot.blob }),
    ]);
    screenshotCopied.value = true;
    return true;
  } catch {
    screenshotCopied.value = false;
    return false;
  }
}

async function captureScreen() {
  if (!navigator.mediaDevices?.getDisplayMedia) {
    error.value = "当前浏览器不支持屏幕捕获,请粘贴或选择图片";
    return;
  }
  let stream = null;
  try {
    stream = await navigator.mediaDevices.getDisplayMedia({
      video: true,
      audio: false,
    });
    const video = document.createElement("video");
    video.srcObject = stream;
    video.muted = true;
    await video.play();
    await new Promise((resolve) => {
      if (video.readyState >= 2) {
        resolve();
        return;
      }
      video.onloadeddata = () => resolve();
    });
    await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
    const scale = Math.min(
      1,
      MAX_SHOT_EDGE / Math.max(video.videoWidth, video.videoHeight)
    );
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.round(video.videoWidth * scale));
    canvas.height = Math.max(1, Math.round(video.videoHeight * scale));
    canvas.getContext("2d").drawImage(video, 0, 0, canvas.width, canvas.height);
    const blob = await new Promise((resolve, reject) => {
      canvas.toBlob(
        (b) => (b ? resolve(b) : reject(new Error("生成截图失败"))),
        "image/png"
      );
    });
    setShot(blob, "screen-capture.png");
  } catch (e) {
    if (e?.name !== "NotAllowedError") {
      error.value = `屏幕捕获失败:${e.message || e}`;
    }
  } finally {
    stream?.getTracks().forEach((track) => track.stop());
  }
}

function pickFile() {
  fileInput.value?.click();
}

function onFilePicked(event) {
  const file = event.target.files?.[0];
  if (file) importImage(file);
  event.target.value = "";
}

function removeShot() {
  revokeShot();
  screenshot.value = null;
  screenshotCopied.value = false;
}

function onPaste(event) {
  const items = event.clipboardData?.items || [];
  for (const item of items) {
    if (item.type.startsWith("image/")) {
      const file = item.getAsFile();
      if (file) {
        event.preventDefault();
        importImage(file);
        return;
      }
    }
  }
}

function onDrop(event) {
  event.preventDefault();
  dropActive.value = false;
  const file = event.dataTransfer?.files?.[0];
  if (file) importImage(file);
}

function onDragOver(event) {
  event.preventDefault();
  dropActive.value = true;
}

function onDragLeave() {
  dropActive.value = false;
}

// ---------------------------------------------------------------- 日志与提交

async function loadLogs() {
  try {
    const data = await feedbackLogs(200);
    if (!alive) return;
    logLines.value = data.lines || [];
    logTotal.value = data.total ?? logLines.value.length;
  } catch {
    /* 后端不可达:反馈仍可生成,只是没有后端日志 */
  }
}

function blobToDataUrl(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(new Error("读取截图失败"));
    reader.readAsDataURL(blob);
  });
}

async function openIssue() {
  if (!description.value.trim()) {
    error.value = "请先描述遇到的问题";
    return;
  }
  error.value = "";
  notice.value = "";
  fallbackUrl.value = "";
  busy.value = true;
  // 同步开窗,避免 await 后弹窗被浏览器拦截
  const win = window.open("", "_blank");
  try {
    if (screenshot.value) copyShot();
    const result = await submitFeedback({
      title: title.value,
      description: description.value,
      include_logs: includeLogs.value,
      log_lines: 200,
      screenshot_data_url: screenshot.value
        ? await blobToDataUrl(screenshot.value.blob)
        : null,
      client: clientContext({
        loggedIn: loggedIn.value,
        neteaseLoggedIn: neteaseLoggedIn.value,
        track: store.currentTrack,
        playing: store.playing,
        quality: store.currentQualityLabel,
        mv: store.mvEnabled && !!store.currentVideoStream,
      }),
    });
    if (win && !win.closed) win.location.href = result.issue_url;
    else fallbackUrl.value = result.issue_url;
    notice.value = result.screenshot_saved
      ? "已打开 GitHub 预填 issue;截图已复制,在 issue 正文里按 Ctrl+V 粘贴即可附图。"
      : "已打开 GitHub 预填 issue。";
    if (result.bundle_path) {
      notice.value += ` 诊断包已保存到 ${result.bundle_path}。`;
    }
  } catch (e) {
    if (win) win.close();
    error.value = e.message || "生成反馈失败";
  } finally {
    busy.value = false;
  }
}

function onKeydown(event) {
  if (event.key === "Escape" && !busy.value) emit("close");
}

onMounted(() => {
  window.addEventListener("paste", onPaste);
  window.addEventListener("keydown", onKeydown);
  feedbackInfo()
    .then((data) => {
      if (alive) meta.value = data;
    })
    .catch(() => {});
  authStatus()
    .then((data) => {
      if (alive) loggedIn.value = !!data.logged_in;
    })
    .catch(() => {});
  neteaseStatus()
    .then((data) => {
      if (alive) neteaseLoggedIn.value = !!data.logged_in;
    })
    .catch(() => {});
  loadLogs();
});

onUnmounted(() => {
  alive = false;
  window.removeEventListener("paste", onPaste);
  window.removeEventListener("keydown", onKeydown);
  revokeShot();
});
</script>

<template>
  <div class="mask" @click.self="emit('close')">
    <div class="dialog">
      <div class="head">
        <span class="title">反馈问题</span>
        <span class="repo-tag">{{ meta.repo }}</span>
        <button class="close-btn" title="关闭" @click="emit('close')">✕</button>
      </div>

      <div class="body">
        <label class="field">
          <span class="label">标题(可选,留空自动生成)</span>
          <input
            v-model="title"
            type="text"
            maxlength="120"
            placeholder="例如:MV 模式切歌后没有下一首"
          />
        </label>

        <label class="field">
          <span class="label">问题描述 <em>必填</em></span>
          <textarea
            v-model="description"
            rows="4"
            maxlength="8000"
            placeholder="出现问题时你在做什么?期望结果与实际结果是什么?"
          ></textarea>
        </label>

        <div class="field">
          <span class="label">截图(可选)</span>
          <div
            class="shot-zone"
            :class="{ active: dropActive, has: screenshot }"
            @dragover="onDragOver"
            @dragleave="onDragLeave"
            @drop="onDrop"
          >
            <template v-if="screenshot">
              <img class="shot-preview" :src="screenshot.url" alt="截图预览" />
              <div class="shot-actions">
                <button class="ghost" @click="copyShot">复制截图</button>
                <button class="ghost" @click="pickFile">换一张</button>
                <button class="ghost" @click="removeShot">移除</button>
              </div>
              <div class="hint" :class="{ ok: screenshotCopied }">
                {{
                  screenshotCopied
                    ? "截图已复制,提交后在 issue 里按 Ctrl+V 粘贴即可"
                    : "浏览器未授权剪贴板:提交后可从诊断包把截图拖进 issue"
                }}
              </div>
            </template>
            <template v-else>
              <div class="shot-empty">
                <button class="primary" @click="captureScreen">截取屏幕</button>
                <button class="ghost" @click="pickFile">选择图片</button>
              </div>
              <div class="hint">
                也可以直接 Ctrl+V 粘贴截图,或把图片拖到这里
              </div>
            </template>
          </div>
          <input
            ref="fileInput"
            class="file-input"
            type="file"
            accept="image/*"
            @change="onFilePicked"
          />
        </div>

        <div class="field logs-field">
          <label class="checkbox">
            <input v-model="includeLogs" type="checkbox" />
            附带最近日志({{ logTotal }} 行,自动脱敏)
          </label>
          <button class="link-btn" @click="showLogs = !showLogs">
            {{ showLogs ? "收起日志" : "查看脱敏后的日志" }}
          </button>
        </div>
        <pre v-if="showLogs" class="log-preview">{{ logLines.join("\n") || "(暂无后端日志)" }}</pre>

        <div v-if="error" class="error">{{ error }}</div>
        <div v-if="notice" class="notice">{{ notice }}</div>
        <a
          v-if="fallbackUrl"
          class="fallback"
          :href="fallbackUrl"
          target="_blank"
          rel="noopener"
        >
          浏览器拦截了弹窗,点此手动打开 GitHub issue
        </a>
      </div>

      <div class="foot">
        <span class="foot-hint">
          提交在 GitHub 页面完成;描述、环境信息和日志会预填进去,提交前可再检查修改。
        </span>
        <button class="ghost" @click="emit('close')">取消</button>
        <button class="primary" :disabled="!canSubmit" @click="openIssue">
          {{ busy ? "正在生成…" : "打开 GitHub issue" }}
        </button>
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
  width: 680px;
  max-width: calc(100vw - 32px);
  max-height: 88vh;
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
  flex-shrink: 0;
}
.title {
  font-size: 16px;
  font-weight: 600;
}
.repo-tag {
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
.body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding-right: 4px;
}
.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.label {
  font-size: 12px;
  color: var(--text-dim);
}
.label em {
  font-style: normal;
  color: var(--accent);
}
.field input[type="text"],
.field textarea {
  padding: 9px 10px;
  border-radius: 8px;
  border: 1px solid var(--border);
  background: var(--panel-2);
  color: var(--text);
  outline: none;
  font-size: 13px;
  resize: vertical;
}
.field input[type="text"]:focus,
.field textarea:focus {
  border-color: var(--accent);
}

.shot-zone {
  border: 1px dashed var(--border);
  border-radius: 10px;
  padding: 14px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  transition: border-color 0.15s, background 0.15s;
}
.shot-zone.active {
  border-color: var(--accent);
  background: var(--accent-soft);
}
.shot-zone.has {
  align-items: stretch;
}
.shot-preview {
  max-width: 100%;
  max-height: 240px;
  margin: 0 auto;
  object-fit: contain;
  border-radius: 8px;
  border: 1px solid var(--border);
  background: #000;
}
.shot-empty {
  display: flex;
  gap: 8px;
}
.shot-actions {
  display: flex;
  gap: 8px;
  justify-content: center;
}
.hint {
  font-size: 12px;
  color: var(--text-dim);
  text-align: center;
}
.hint.ok {
  color: #6fd08c;
}
.file-input {
  display: none;
}

.logs-field {
  flex-direction: row;
  align-items: center;
  gap: 12px;
}
.checkbox {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--text-dim);
}
.link-btn {
  font-size: 12px;
  color: var(--accent);
}
.log-preview {
  flex-shrink: 0;
  height: 170px;
  overflow: auto;
  padding: 10px;
  border-radius: 8px;
  border: 1px solid var(--border);
  background: #0b0b10;
  color: #b9b9c6;
  font-size: 11px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-all;
}
.error {
  color: #e56d6d;
  font-size: 12px;
}
.notice {
  color: #6fd08c;
  font-size: 12px;
  line-height: 1.5;
  word-break: break-all;
}
.fallback {
  color: var(--accent);
  font-size: 12px;
}

.foot {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: 10px;
  padding-top: 14px;
  margin-top: 12px;
  border-top: 1px solid var(--border);
}
.foot-hint {
  flex: 1;
  font-size: 11px;
  color: var(--text-dim);
  line-height: 1.5;
}
.primary {
  padding: 7px 18px;
  border-radius: 15px;
  background: var(--accent);
  color: #fff;
  font-size: 13px;
  white-space: nowrap;
}
.primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.ghost {
  padding: 7px 16px;
  border-radius: 15px;
  border: 1px solid var(--border);
  color: var(--text-dim);
  font-size: 13px;
  white-space: nowrap;
}
.ghost:hover {
  color: var(--accent);
  border-color: var(--accent);
}
</style>
